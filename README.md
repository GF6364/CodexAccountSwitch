# Codex 账号切换器

一个面向 VS Code Codex 使用场景的本地账号管理工具。

## 能做什么

- 保存当前已登录的 Codex 账号数据
- 展示本地保存过的账号列表
- 按账号快速还原登录数据
- 删除不再需要的本地账号记录
- 查看当前账号的额度信息
- 给已保存账号单独获取额度信息
- 本地保存普通额度的已用比例和刷新倒计时

## 界面功能

- 保存当前登录数据
- 刷新当前登录信息
- 获取当前额度
- 查看已保存账号列表
- 右键对账号执行还原、获取额度、删除
- 查看选中账号详情

## 命令行功能

- `python main.py gui` 启动图形界面
- `python main.py status` 查看当前登录状态
- `python main.py list` 查看已保存账号列表
- `python main.py save` 保存当前登录数据
- `python main.py quota` 查看当前额度
- `python main.py quota --json` 输出原始额度 JSON
- `python main.py restore <snapshot_id>` 还原指定账号
- `python main.py delete <snapshot_id>` 删除指定账号

## 使用要求

- Windows
- Python 3.8+
- 已在本机登录过 Codex

## 快速开始

```powershell
python main.py
```

或

```powershell
python main.py gui
```

## 说明

- 项目只上传源码，不包含你的本地账号数据
- 本地缓存、备份和打包产物已加入忽略列表

## 截图与视频

- 预留位置：可在仓库后续补充界面截图和操作视频