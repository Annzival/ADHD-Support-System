# V-05 恢复干预载体原型

> **PROTOTYPE — 非生产实现。** 此目录是 Issue #7 的一次性低保真交互证据，不接入 Wails、Python Core、SQLite、真实系统通知或任何生产领域逻辑。

## 运行

在仓库根目录执行：

```bash
python3 -m http.server 4173 --directory prototypes/v05-recovery-intervention
```

打开 [http://localhost:4173/?variant=A&scenario=active-session](http://localhost:4173/?variant=A&scenario=active-session)。

可分享的 URL 参数：

- `variant=A`：主窗口主导；
- `variant=B`：置顶小窗主导；
- `variant=C`：系统通知主导；
- `scenario=active-session`、`resume-packet`、`missed-start`、`merged-expired`、`after-current-plan` 或 `after-defer`。

也可以用页面底部的切换栏或左右方向键切换方案；输入框和文本框获得焦点时，方向键不会切换。

## 走查边界

三种方案都模拟主窗口、置顶小窗和系统通知，并将所有交互保存在浏览器内存。右侧会显示完整模拟状态；“记录本次观察”会在本页汇总可复制的体验记录，但不会写入磁盘或网络。

建议第一轮按页面列出的四步分别走查三个方案，重点记录：

1. 是否能区分上次执行上下文与当前计划；
2. 是否把“继续上次执行”和“处理上一项”理解为不同操作；
3. 是否误以为失效干预意味着上一项被放弃；
4. 是否觉得系统通知或置顶小窗会抢焦点；
5. 选择“暂不决定”后是否能在主窗口找到被动入口。

本原型不能证明真实 Windows 通知操作、置顶行为或焦点策略；这些限制会在结果文档中单独记录，不能从模拟体验外推。
