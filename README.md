# `IIS` Auto Recover  

 基于`Ansible`实现尝试自动修复。
 
 如果在一分钟之内检测的站点后端`HTTP`响应状态码为`5XX`或者响应超时，并累计达到指定次数。将自动执从`NGINX`中下线主机，
 并重启后端`IIS`站点。 
 
 特性:
 - `aiohttp`异步检测
 - 异常自动下线主机并重启后端`IIS`站点
 - 持续尝试自动重启，两次间隔时间为`100`秒，防止恶性循环
 - 恢复后自动加入`NGINX`后端负载
 - 支持多站点部署主机
 - 事件通知
 

## 工作流程图
![流程图](images/work-flow.jpg)

## 部署

### 准备配置文件

config.yml

```yaml
sites:
   - site: www.aaa.com
    # 检测响应超时时间，秒
    timeout: 5
    # 一分钟之内最大允许的异常状态次数,达到后会采取动作
    max_failed: 5
    # 最大允许下线的主机，达到该值后，新主机即使异常也不执行任何动作,但会发送通知。
    # 如果该值和服务器数量一样多，就不执行动作，只发送通知
    # 未指定时，默认为len(servers) // 2
    max_inactive: 1
    # 通过读取NGINX中的配置文件来获取后端Servers，但要求后端端口要一致
    config_file: /etc/nginx/conf.d/www.aaa.com.conf
    # 后端upstream的端口
    backend_port: 80
    # upstream_file与servers同时存在时，优先读取servers里面的值
    servers:
      - 128.0.255.10:9090
      - 128.0.255.10:5000
      - 128.0.255.10:9092
    gateway_type: nginx

# 网关服务器，当前仅支持NGINX
nginxs:
  - 128.0.255.10
  - 128.0.100.170

# 异常通知，如果填三个，将发三种消息
notify:
  # 微信
  wechat:
    corpid: wechat-corpid
    secret: wechat-secret
    users:
      - user1
      - user2

  # 邮件
  email:
    server: smtp.domain.com
    username: username
    password: password
    users:
      - username@domain.com
      - user2@domain.com

  # 钉钉
  dingding:
    # 钉钉讨论组中的机器人的TOKEN。可以通过创建讨论组后，添加机器人
    robot_token: token
```

### 编译镜像

```bash
cd ProjectDir
docker build -t monitor .
```

###  docker-compose.yml
```yaml
monitor:
    image: monitor
    container_name: monitor
    net: host
    restart: always
    volumes:
      - ./ansible_hosts:/etc/ansible/hosts
      - ./config.yml:/opt/app/config.yml
```

## Example Files

### ansible_hosts

```ini
[linux]
# 该主机名称要同config.yml中的servers值一致
128.0.100.170 ansible_user=username ansilbe_password=password
128.0.255.10  ansible_user=username ansilbe_password=password

[windows]
192.168.1.10 ansible_password=password

[windows:vars]
ansible_user=administrator
ansible_connection=winrm
ansible_winrm_transport=basic
ansible_port=5986
ansible_winrm_scheme=https
ansible_winrm_server_cert_validation=ignore
```

如果需要部分自动执行，另一些不自动，可以将`Ansible`的主机清单文件中，不想自动干预的主机注释