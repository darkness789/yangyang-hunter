# 羊羊狩猎者

《羊了个羊：星球》微信小游戏的 Windows 桌面通关辅助。玩家自己点击游戏；程序读取关卡地图、计算路线，在游戏窗口上标出下一张牌，并通过鼠标位置和画面变化同步进度。目前只辅助第二关，第一关由玩家自行完成。

项目在一局 225 张牌的第二关上完成过真实通关。那局使用了一次“移出”和一次“复活”；求解器支持这两种道具，以及从移出区取回卡牌。规划时会尝试不同的搜索顺序、分支宽度、道具使用时机，并在深度搜索失败后尝试保留多种局面的搜索。后续关卡是否能找到路线仍取决于地图和搜索预算，程序不会把超时当作“无解”。

当前本机捕获的一局 216 张牌地图仍未在测试预算内找到完整路线；这不构成无解证明。遇到此提示时可在当前局面点击“重新规划”继续尝试。随机洗牌会改变牌型分布，目前未纳入自动规划。

## 准备环境

- Windows 和电脑版微信，能打开《羊了个羊：星球》小游戏。
- Python 3.7+；运行 `python -m pip install -r requirements.txt` 安装 Pillow。
- Node.js，用于按种子还原牌面。
- mitmproxy 的 `mitmdump.exe`。当前脚本按 `C:\Program Files\mitmproxy\bin\mitmdump.exe` 查找；安装在别处时修改 [start_capture.ps1](scripts/start_capture.ps1) 中的路径。首次使用需运行一次 `mitmdump` 生成证书。
- 抓包脚本默认通过 `http://127.0.0.1:12000` 上游代理转发。没有该代理时，需要按本机网络环境调整 [start_capture.ps1](scripts/start_capture.ps1) 的 `UpstreamProxy` 或抓包模式。

## 使用

在项目目录运行：

```powershell
pythonw -m yangyang_hunter
```

在辅助界面点击“监听下一局”，然后进入小游戏。程序获取本局种子后，会在本地恢复牌面并搜索路线。第一关不会显示提示；进入第二关后，红圈标出建议点击的牌。保持“自动识别我在游戏中的点击”勾选即可按提示手动点击。

遇到新的第二关地图时，程序会继续等待该局的 `.map` 抓包，自动解码并保存在本机；如果游戏直接使用缓存、抓包里没有地图，则根据本局地图编号从游戏静态资源地址下载。已经出现“新关卡准备失败”时，重启新版界面后点“重新规划”，可直接使用 `captures/` 中最近一次的种子和地图重试，无需重新开局。地图恢复成功不保证搜索预算内一定找到路线；未找到时界面会明确提示。

路线要求使用道具时，界面会显示“移出”或“复活”。“移出”后会定位移出区的三列牌，并跟踪在该区域的点击；“复活”目前需要在游戏中操作后点击“确认这步已完成”。如果某次点击没有同步，可用“确认这步已完成”“撤销识别”或下拉框“补记这张牌”修正。

从已有的本地地图和路线继续时，可传入 `--map`、`--tool-solution` 和 `--resume`。`--resume` 是已经完成的**操作数**，包括道具操作。关卡文件和路线保存在本机的 `captures/`，本仓库不会上传这些数据。

## 工作原理

1. [capture_map.py](yangyang_hunter/capture_map.py) 和 [seed_probe.py](yangyang_hunter/seed_probe.py) 通过 mitmproxy 获取关卡地图与本局种子。只保存需要的响应数据，并过滤常见身份字段。
2. [map_templates.py](yangyang_hunter/map_templates.py) 查找或获取本局地图，[decode_map.py](yangyang_hunter/decode_map.py) 解析地图；[restore_types.js](scripts/restore_types.js) 依据种子还原每张牌的图案。`yangyang_hunter/templates/` 放有已知地图结构模板，不含用户凭据；新地图只保存在本机 `captures/`。
3. [board_model.py](yangyang_hunter/board_model.py)、[solve.py](yangyang_hunter/solve.py) 和 [solve_with_tools.py](yangyang_hunter/solve_with_tools.py) 建模遮挡、七格槽和道具，搜索并重放验证路线。
4. [desktop_assistant.py](yangyang_hunter/desktop_assistant.py) 显示下一步，监听玩家在游戏窗口中的点击，检查画面变化后推进或重新规划。它不会自动向游戏发送点击。

`captures/`、`.env`、证书和本机代理状态均不纳入版本控制。程序依赖当前版本的微信窗口标题、画面布局、种子格式和游戏规则；这些内容更新后可能需要重新校准。

详细设计见 [DESIGN.md](docs/DESIGN.md)。运行 `python -m unittest discover -s tests -q` 可检查基础规则模型。
