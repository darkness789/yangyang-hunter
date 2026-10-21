# 羊羊狩猎者

《羊了个羊：星球》微信小游戏的 Windows 桌面通关辅助。玩家自己点击游戏；程序读取关卡地图、计算路线，在游戏窗口上标出下一张牌，并通过鼠标位置和画面变化同步进度。目前只辅助第二关，第一关由玩家自行完成。

项目在一局 225 张牌的第二关上完成过真实通关。那局使用了一次“移出”和一次“复活”；求解器支持这两种道具，以及从移出区取回卡牌。后续关卡是否能找到路线取决于地图和搜索预算，程序不会把超时当作“无解”。

## 准备环境

- Windows 和电脑版微信，能打开《羊了个羊：星球》小游戏。
- Python 3.7+；运行 `python -m pip install -r requirements.txt` 安装 Pillow。
- Node.js，用于按种子还原牌面。
- mitmproxy 的 `mitmdump.exe`。当前脚本按 `C:\Program Files\mitmproxy\bin\mitmdump.exe` 查找；安装在别处时修改 [start_capture.ps1](start_capture.ps1) 中的路径。首次使用需运行一次 `mitmdump` 生成证书。
- 抓包脚本默认通过 `http://127.0.0.1:12000` 上游代理转发。没有该代理时，需要按本机网络环境调整 [start_capture.ps1](start_capture.ps1) 的 `UpstreamProxy` 或抓包模式。

## 使用

在项目目录运行：

```powershell
pythonw .\desktop_assistant.py
```

在辅助界面点击“监听下一局”，然后进入小游戏。程序获取本局种子后，会在本地恢复牌面并搜索路线。第一关不会显示提示；进入第二关后，红圈标出建议点击的牌。保持“自动识别我在游戏中的点击”勾选即可按提示手动点击。

路线要求使用道具时，界面会显示“移出”或“复活”。“移出”后会定位移出区的三列牌，并跟踪在该区域的点击；“复活”目前需要在游戏中操作后点击“确认这步已完成”。如果某次点击没有同步，可用“确认这步已完成”“撤销识别”或下拉框“补记这张牌”修正。

从已有的本地地图和路线继续时，可传入 `--map`、`--tool-solution` 和 `--resume`。`--resume` 是已经完成的**操作数**，包括道具操作。关卡文件和路线保存在本机的 `captures/`，本仓库不会上传这些数据。

## 工作原理

1. [capture_map.py](capture_map.py) 和 [seed_probe.py](seed_probe.py) 通过 mitmproxy 获取关卡地图与本局种子。只保存需要的响应数据，并过滤常见身份字段。
2. [decode_map.py](decode_map.py) 解析地图；[tools/restore_types.js](tools/restore_types.js) 依据种子还原每张牌的图案。`templates/` 放有当前版本的两张地图结构模板，不含用户凭据。
3. [board_model.py](board_model.py)、[solve.py](solve.py) 和 [solve_with_tools.py](solve_with_tools.py) 建模遮挡、七格槽和道具，搜索并重放验证路线。
4. [desktop_assistant.py](desktop_assistant.py) 显示下一步，监听玩家在游戏窗口中的点击，检查画面变化后推进或重新规划。它不会自动向游戏发送点击。

`captures/`、`.env`、证书和本机代理状态均不纳入版本控制。地图模板如果随游戏更新，需要重新抓取和解析。程序依赖当前版本的微信窗口标题、画面布局和游戏规则；这些内容更新后可能需要重新校准。

详细设计见 [DESIGN.md](DESIGN.md)。运行 `python -m unittest test_board_model -q` 可检查基础规则模型。
