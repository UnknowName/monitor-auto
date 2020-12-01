# `IIS` Auto Recover  

 基于`Ansible`实现尝试自动修复。
 
 如果在一分钟之内检测的站点后端`HTTP`响应状态码为`5XX`或者响应超时，并累计达到指定次数。将自动执从`NGINX`中下线主机，
 并重启后端`IIS`站点。 
 
 特性:
 - `aiohttp`异步检测
 - 异常自动从网关中下线主机并重启后端`IIS`站点
 - 可指定间隔时间，默认为`300`秒，防止恶性循环
 - 恢复后自动加入网关后端负载
 - 支持`NGINX`与阿里云`SLB`网关类型
 - 支持微信、邮件、钉钉事件通知
 

## 工作流程图
![流程图](images/work-flow.jpg)

## 部署

### 准备配置文件

config.yml

```yaml
sites:
  - site: www.aaa.com
    # 是否尝试自动恢复，重启站点,默认为False
    auto_recover: True
    # 尝试自动恢复的动作间隔，默认300秒
    auto_inter: 300
    # 检查超时,默认为5秒
    timeout: 5
    # HTTP检查路径，如不指定，默认为/
    path: /
    # 一分钟之内最大允许的异常状态次数,达到后会采取动作
    max_failed: 5
    # 最大允许下线的主机，达到该值后，新主机即使异常也不执行任何动作,只发送异常通知。
    # 如果不指定，则取len(servers) // 2
    max_inactive: 1
    # 通过读取NGINX中的配置文件来获取后端Servers，但要求后端端口要一致
    gateway_type: nginx
    config_file: /etc/nginx/conf.d/www.aaa.com.conf
    # 当使用NGINX获取后端时，backend_port必须配置
    backend_port: 80
    # servers同时存在时，优先级最高，不会从网关或SLB中读取后端信息
    servers:
      - 128.0.255.10:9090
      - 128.0.255.10:9095
      - 128.0.255.10:9093
    # 仅支持阿里云的SLB与NGINX
    # gateway_type: slb
    # listen_port: 443
    # slb_id: xxxxx

  - site: test.bbb.com
    auto_recover: True
    max_failed: 7
    timeout: 5
    # 不要 >= len(servers)!
    max_inactive: 1
    # servers:
    #  - 128.0.255.30:80
    gateway_type: nginx
    config_file: /etc/nginx/conf.d/www.aaa.com.conf
    backend_port: 80
    servers:
      - 128.0.100.171:90
      - 128.0.100.178:80

  - site: test.aaa.com
    max_failed: 7
    timeout: 5
    max_inactive: 1
    gateway_type: slb
    listen_port: 80
    slb_id: 1100000222

gateway:
  nginx:
    user: username
    # 暂不支持密码，未使用pam模块
    # password: password
    hosts:
    # 如果两台是一样，一台就可以，如果多台不一样，取合集
    - 128.0.255.10
    - 128.0.255.11

  slb:
    key: key
    secret: secret
    region: cn-hz

notify:
#  wechat:
#    corpid: wechat-corpid
#    secret: wechat-secret
#    users:
#      - tkggvfhpce2
#      - user2

#  email:
#    server: smtp.domain.com
#    username: username
#    password: password
#    users:
#      - username@domain.com
#      - user2@domain.com

 -  type: dingding
    robot_token: 201ce5cecb1343bbb6d59550efbca1567c2b08ea8843d966f1c76b309308c25b5
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