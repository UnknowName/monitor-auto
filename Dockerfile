FROM python:3.7-alpine
ENV APP_HOME=/opt/app \
    TZ=Asia/Shanghai \
    PATH=${APP_HOME}/bin:$PATH
ADD ./rebuild /opt/app/src
ADD ./Pipfile /opt/app/src
WORKDIR /opt/app/src
RUN adduser -D -u 120002 -h /opt/app/ app \
    && mkdir ../.ssh \
    && mkdir ../tasks_yaml \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories \
    && apk add gcc g++ make libffi-dev openssl-dev tzdata openssh-client sshpass \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ pipenv pywinrm ansible \
    && pipenv lock \
    && pipenv install --system --deploy \
    && apk del gcc g++ make libffi-dev openssl-dev \
    && rm -rf /var/cache/apk/*
RUN chown -R app:app /opt/app \
    && echo -e "StrictHostKeyChecking no\nUserKnownHostsFile /dev/null" >> /etc/ssh/ssh_config \
    && chmod 600 -R /opt/app/.ssh
USER app
CMD ["python", "-u", "main.py"]