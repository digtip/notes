---
title: 日常写作与发布流程
tags:
  - 工作流
  - 写作
---

# 日常写作与发布流程

> [!important] 单向写入
> 只从本地推送到 Gitee；GitHub 是只读镜像，禁止在 GitHub 网页端编辑。

## 1. 创建草稿

在 `learn/` 中提供主题、真实操作记录、命令、报错与截图。向 Hermes 说：

> 根据 `learn/<文件名>.md` 规划一篇 `<kirin/ai/dev>` 博文大纲，不补造技术事实。

## 2. 分章节成文

按「背景 → 环境信息 → 操作步骤 → 命令清单 → 坑点与排错 → 总结」分章节扩写。信息不足保留【待补充】标记。

## 3. 人工校验并定稿

- [ ] 命令已在所述环境实际执行。
- [ ] 系统版本、报错、路径准确，没有混入其他发行版内容。
- [ ] 截图来自本人实操，敏感信息已脱敏。
- [ ] 移动到 `blog/<专题>/`，更新对应专题 `README.md` 目录。

## 4. 提交到 Gitee

让 Hermes 检查变更并提交，例如：

> 提交这篇定稿博文到 Gitee，先展示变更摘要。

```bash
git pull --ff-only origin main
git add blog/<专题>/<文章>.md blog/<专题>/README.md
git commit -m "blog(<专题>): <文章标题>"
git push origin main
```

## 5. 验证后分发

- [ ] Gitee 已成功接收 `main` 分支。
- [ ] Gitee → GitHub 镜像同步成功。
- [ ] Gitee Pages 已更新并能打开原文。
- [ ] 再发布到 CSDN，随后同步掘金、麒麟论坛等平台。

文末引用：

```markdown
> 本文原文托管于 Gitee Pages：
> https://digtip.gitee.io/notes/blog/<专题>/<文章文件名>
> 完整实操命令、配置与素材见仓库；GitHub 为只读镜像备份。
```

## 常用交互指令

- **写大纲**：`根据 learn/xxx.md 生成博文大纲`
- **写一章节**：`只扩写这篇文章的“操作步骤”章节，保留命令原样`
- **准备定稿**：`检查事实待补项并更新专题目录，不提交`
- **提交发布**：`展示本次变更摘要，经我确认后提交并推送 Gitee`
- **检查发布**：`检查 Gitee、GitHub 镜像和 Pages 的发布状态`
