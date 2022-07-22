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
default:
  # 60秒内累计7次
  duration: 60
  timeout: 5
  max_failed: 5
  path: /
  # 自动干预间隔时间，防止恶性循环
  auto_interval: 200
  max_inactive: 1
  recover: False
  check_interval: 1

sites:
  - site: www.aaa.com
    # 具体怎么Recover不管，要具体实现一个AbstractRecoverAction
    recover:
      enable: True
      # 类型，暂支持restart_process与restart_website
      type: restart_process
      name: httpd.exe
    gateway:
      type: nginx
      upstream_port: 9090
      config_file: /etc/nginx/conf.d/www.aaa.com.conf

  - site: test.bbb.com
    max_failed: 12
    timeout: 3
    check_method: post
    post_data:
      key1: value1
      key2: value2
    gateway:
     # 指定后端servers，表示不从网关中获取
      type: static
      servers:
      - 128.0.100.171:80
      - 128.0.100.178:80

  - site: test.aaa.com
    gateway:
      type: slb
      id: 1100000222
      # 前端监听的端口
      port: 80

gateway:
  nginx:
    user: root
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
  - type: dingding
    token: 201ce5cecb1343bbb6d59550efbca1567c2b08ea8843d966f1c76b309308c25b5

  - type: wechat
    secret: secret
    corp_id: asekey
    users:
      - user1
      - user2
```

### 编译镜像

```bash
cd ProjectDir
docker build -t monitor-auto .
```

###  docker-compose.yml
```yaml
monitor:
    image: monitor-auto
    container_name: monitor-auto
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

# TODO

- 阿里云`SLB`网关类型支持代码实现