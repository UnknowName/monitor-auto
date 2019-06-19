# 监控URL

 基于`Ansible`实现尝试自动修复。
 
 首次将通过`Ansible`执行回收操作。
 如果回收过后，三分钟之内仍然不见效。将执行从`NGINX`中摘除操作
 

## 工作流程图
![流程图](images/work-flow.jpg)

## 部署

### 编译镜像

```bash
cd ProjectDir
docker build -t monitor .
```

###  docker-compose.yml
```yaml
monitor:
    image: monitor
    net: host
    restart: always
    volumes:
      - ./ansible_hosts:/etc/ansible/hosts
      - ./hosts:/etc/hosts
```