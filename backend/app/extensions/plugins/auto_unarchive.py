import logging
import os
import re
import time


logger = logging.getLogger(__name__)


class Auto_unarchive:
    default_config = {
        "tips_": "自动云解压(zip|rar|7z)到保存目录，在任务插件选项中启用，该功能需SVIP支持",
        "global_enable": False,  # 是否全局开启自动解压
        "max_concurrent": 3,  # 限制同时解压的任务数
    }

    default_task_config = {
        "enable": False,  # 是否自动解压
        "auto_clean": True,  # 是否自动删除原始文件
        "auto_clean_zipdir": True,  # 是否删除占位目录，适用于一次性运行的任务，无须防止重复转存的占位目录
    }

    is_active = True  # 默认全局激活，由任务配置中开启

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.__name__.lower()
        if kwargs:
            for key, _ in self.default_config.items():
                if key in kwargs:
                    setattr(self, key, kwargs[key])

    def run(self, task, **kwargs):
        account = kwargs.get("account")
        tree = kwargs.get("tree")

        task_config = task.get("addition", {}).get(self.plugin_name, self.default_task_config)

        if not str(self.global_enable).lower() == "true":
            if not task_config.get("enable"):
                logger.info(
                    "🟨 [%s] 未启用 auto_unarchive（任务插件选项 enable=false，且 global_enable 未开启）",
                    task.get("taskname", ""),
                )
                return task

        # 任务配置中是否自动删除原始文件
        self.auto_clean = task_config.get("auto_clean", True)
        self.auto_clean_zipdir = task_config.get("auto_clean_zipdir", False)
        logger.info(
            "📦 [%s] auto_unarchive 启动: enable=%s auto_clean=%s auto_clean_zipdir=%s global_enable=%s",
            task.get("taskname", ""),
            task_config.get("enable"),
            self.auto_clean,
            self.auto_clean_zipdir,
            getattr(self, "global_enable", None),
        )

        try:
            savepath = re.sub(r"/{2,}", "/", f"/{task['savepath']}")
            target_pdir_fid = account.savepath_fid.get(savepath)
            logger.info(
                "📂 [%s] 云解压目标目录: savepath=%s target_pdir_fid=%s",
                task.get("taskname", ""),
                savepath,
                target_pdir_fid,
            )

            if not target_pdir_fid:
                logger.warning("🟨 [%s] 未找到保存目录 fid，跳过云解压：%s", task.get("taskname", ""), savepath)

            drive_type = getattr(account, "DRIVE_TYPE", "") or ("quark" if account.__class__.__name__ == "Quark" else "")
            if drive_type and drive_type not in {"quark", "uc"}:
                logger.warning("⚠️ [%s] %s 网盘未适配云解压，跳过插件执行", task["taskname"], drive_type)
                return task

            # 获取待解压节点列表
            all_zip_nodes = [
                node
                for node in tree.all_nodes()
                if node.data
                and not node.data.get("is_dir")
                and re.search(r"\.(zip|rar|7z)$", node.tag, re.I)
            ]
            logger.info(
                "🔎 [%s] 检测到压缩包节点: %s",
                task.get("taskname", ""),
                [
                    {
                        "tag": node.tag,
                        "fid": node.data.get("fid"),
                        "file_name": node.data.get("file_name"),
                        "file_name_re": node.data.get("file_name_re"),
                    }
                    for node in all_zip_nodes
                ],
            )
            if not all_zip_nodes:
                logger.info("🟨 [%s] 未发现压缩包（zip|rar|7z），跳过云解压", task.get("taskname", ""))
                return task

            wait_list = all_zip_nodes.copy()  # 等待提交队列
            active_tasks = []  # 正在解压队列
            all_move_fids = []
            all_cleanup_fids = []

            logger.info("📦 [%s] 共有 %s 个任务，控制并发数为: %s", task["taskname"], len(wait_list), self.max_concurrent)

            while wait_list or active_tasks:

                while len(active_tasks) < int(self.max_concurrent) and wait_list:
                    node = wait_list.pop(0)
                    zip_fid = node.data["fid"]
                    zip_name = node.data.get("file_name_re") or node.data.get("file_name") or node.tag
                    main_name = os.path.splitext(zip_name)[0]
                    logger.info(
                        "  📝 准备提交解压: zip_fid=%s zip_name=%s raw_name=%s main_name=%s",
                        zip_fid,
                        zip_name,
                        node.data.get("file_name"),
                        main_name,
                    )

                    res = account.unarchive(zip_fid, target_pdir_fid)
                    logger.info("  📮 提交解压响应: zip_name=%s response=%s", zip_name, res)
                    if res.get("code") == 0:
                        task_id = res["data"]["task_id"]
                        active_tasks.append(
                            {
                                "task_id": task_id,
                                "zip_fid": zip_fid,
                                "main_name": main_name,
                                "zip_name": zip_name,
                            }
                        )
                        logger.info("  ▶️ 提交解压: %s", zip_name)
                    else:
                        logger.warning("  ❌ 提交失败: %s (%s)", zip_name, res.get("message"))
                        if "concurrent" in res.get("message", ""):
                            wait_list.insert(0, node)
                            break
                    time.sleep(1)

                for p_task in active_tasks[:]:
                    q_res = account.query_task(p_task["task_id"])
                    logger.info(
                        "  📡 查询解压任务: task_id=%s zip_name=%s response=%s",
                        p_task["task_id"],
                        p_task["zip_name"],
                        q_res,
                    )

                    if q_res.get("code") == 0:
                        logger.info("  ✅ 解压完成: %s", p_task["zip_name"])
                        self._process_files(
                            account,
                            p_task,
                            q_res,
                            target_pdir_fid,
                            all_move_fids,
                            all_cleanup_fids,
                        )
                        active_tasks.remove(p_task)
                    elif q_res.get("code") == 1:
                        pass
                    else:
                        logger.warning("  ⚠️ 任务异常: %s %s", p_task["zip_name"], q_res.get("message", ""))
                        active_tasks.remove(p_task)

                if active_tasks:
                    time.sleep(5)

            if all_move_fids:
                logger.info("🚀 任务全部解压完成，开始批量移动 %s 个文件...", len(all_move_fids))
                move_ok = account.move_files(all_move_fids, target_pdir_fid).get("code") == 0
            else:
                move_ok = True

            if move_ok and all_cleanup_fids:
                logger.info("🧹 开始批量清理 %s 个文件/目录...", len(all_cleanup_fids))
                if account.delete(all_cleanup_fids):
                    logger.info("🧹 批量清理完成")
                else:
                    logger.warning("🟨 批量清理失败（delete 返回 False）: %s", all_cleanup_fids)

        except Exception as e:
            logger.exception("❌ 运行异常: %s", e)
        return task

    def _process_files(self, account, p_task, q_res, target_fid, move_list, clean_list):
        """处理文件重命名逻辑"""
        # 获取解压出来压缩包同名目录的fid
        un_list = q_res.get("data", {}).get("unarchive_result", {}).get("list", [])
        logger.info(
            "  📂 处理解压结果: zip_name=%s main_name=%s target_fid=%s unarchive_list=%s",
            p_task["zip_name"],
            p_task["main_name"],
            target_fid,
            [
                {
                    "fid": i.get("fid"),
                    "file_name": i.get("file_name"),
                    "dir": i.get("dir"),
                }
                for i in un_list
                if isinstance(i, dict)
            ],
        )
        sub_dir_fid = next(
            (i["fid"] for i in un_list if p_task["main_name"] == i["file_name"]), None
        )
        if not sub_dir_fid:
            direct_files = [
                i
                for i in un_list
                if isinstance(i, dict) and not bool(i.get("dir")) and str(i.get("fid") or "").strip()
            ]
            logger.warning(
                "  ⚠️ 未找到与压缩包同名的解压目录: zip_name=%s main_name=%s candidates=%s",
                p_task["zip_name"],
                p_task["main_name"],
                [i.get("file_name") for i in un_list if isinstance(i, dict)],
            )
            if not direct_files:
                return
            logger.info(
                "  📄 检测到直出文件模式: zip_name=%s direct_files=%s",
                p_task["zip_name"],
                [
                    {
                        "fid": item.get("fid"),
                        "file_name": item.get("file_name"),
                        "pdir_fid": item.get("pdir_fid"),
                    }
                    for item in direct_files
                ],
            )
            if self.auto_clean:
                clean_list.append(p_task["zip_fid"])
                logger.info("  🧹 直出文件模式，原压缩包加入清理队列: zip_fid=%s", p_task["zip_fid"])
            else:
                logger.info("  ℹ️ 直出文件模式且 auto_clean=false，保留原压缩包: zip_fid=%s", p_task["zip_fid"])

            for item in direct_files:
                item_fid = str(item.get("fid") or "").strip()
                item_pdir_fid = str(item.get("pdir_fid") or "").strip()
                if item_fid and item_pdir_fid and target_fid and item_pdir_fid != str(target_fid):
                    move_list.append(item_fid)
            if direct_files:
                logger.info("  🚚 直出文件模式移动队列: move_list=%s", list(move_list))

            if len(direct_files) == 1:
                item = direct_files[0]
                ext = os.path.splitext(str(item.get("file_name") or ""))[1]
                new_name = f"{p_task['main_name']}{ext}"
                logger.info(
                    "  🏷️ 直出单文件准备重命名: item_fid=%s old_name=%s new_name=%s",
                    item.get("fid"),
                    item.get("file_name"),
                    new_name,
                )
                rename_file_res = account.rename(item["fid"], new_name)
                logger.info("    └─ 直出单文件重命名完成: new_name=%s response=%s", new_name, rename_file_res)
            else:
                logger.info(
                    "  ℹ️ 直出文件模式跳过单文件重命名: zip_name=%s items_count=%s",
                    p_task["zip_name"],
                    len(direct_files),
                )
            return
        logger.info("  📁 命中解压目录: zip_name=%s sub_dir_fid=%s", p_task["zip_name"], sub_dir_fid)

        if self.auto_clean:
            # 压缩包加入清理队列
            clean_list.append(p_task["zip_fid"])
            if self.auto_clean_zipdir:
                # 解压目录加入清理队列
                clean_list.append(sub_dir_fid)
            else:
                # 重命名解压目录为压缩包名称，占位，避免下次重复转存
                rename_dir_res = account.rename(sub_dir_fid, p_task["zip_name"])
                logger.info(
                    "  🏷️ 重命名解压目录用于占位: fid=%s new_name=%s response=%s",
                    sub_dir_fid,
                    p_task["zip_name"],
                    rename_dir_res,
                )
        else:
            # 不自动清理时，原压缩包占位，将解压目录加入清理队列
            clean_list.append(sub_dir_fid)
            logger.info("  ℹ️ auto_clean=false，保留压缩包占位并清理解压目录: sub_dir_fid=%s", sub_dir_fid)

        # 获取解压目录下的所有文件
        ls_res = account.ls_dir(sub_dir_fid)
        items = ls_res.get("data", {}).get("list", [])
        logger.info(
            "  📄 解压目录内容: sub_dir_fid=%s items=%s",
            sub_dir_fid,
            [
                {
                    "fid": item.get("fid"),
                    "file_name": item.get("file_name"),
                    "dir": item.get("dir"),
                }
                for item in items
                if isinstance(item, dict)
            ],
        )
        for item in items:
            move_list.append(item["fid"])
        logger.info("  🚚 已加入移动队列: count=%s move_list=%s", len(items), list(move_list))

        if len(items) == 1:
            item = items[0]
            # 重命名文件 /zip1/xx.mp4 -> /zip1/zip1.mp4
            # 当压缩包里只有一个文件时，执行按压缩包名称重命名
            ext = os.path.splitext(item["file_name"])[1]
            new_name = f"{p_task['main_name']}{ext}"
            logger.info(
                "  🏷️ 准备重命名单文件: item_fid=%s old_name=%s new_name=%s",
                item.get("fid"),
                item.get("file_name"),
                new_name,
            )
            rename_file_res = account.rename(item["fid"], new_name)
            logger.info("    └─ 重命名完成: new_name=%s response=%s", new_name, rename_file_res)
        else:
            logger.info(
                "  ℹ️ 跳过单文件重命名: zip_name=%s items_count=%s",
                p_task["zip_name"],
                len(items),
            )
