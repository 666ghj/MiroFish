# ChatGPT OAuth 页面登录设计

模型配置页选择 ChatGPT OAuth 连接后，通过 MiroFish Backend 安全代理 Direct OAuth Gateway 的 Device Code 登录。OAuth Token、authorization code 和 code verifier 只存在于 Gateway 及其独立 Docker Volume。

Gateway 暴露内网鉴权接口：创建登录、查询登录状态、取消登录、读取脱敏账户、退出登录。创建登录返回 `login_id`、官方授权地址、用户代码、过期时间；后台线程轮询并持久化 Token。状态只允许 `waiting/authenticated/expired/denied/failed/cancelled`。

Backend 使用 `DIRECT_GATEWAY_TOKEN` 请求 Gateway，不记录响应中的用户代码，不接触 Token。前端显示授权地址、用户代码、轮询状态、脱敏邮箱和套餐，支持复制代码、打开官方页面、重新登录和二次确认退出。

同一时间只保留一个活跃登录，过期会话自动清理。Gateway 不映射宿主机端口。
