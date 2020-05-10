FROM python:3.7-alpine
ENV APP_HOME=/opt/app PATH=${APP_HOME}/bin:$PATH
ADD ./src /opt/app/src
ADD ./Pipfile /opt/app/src
WORKDIR /opt/app/src
RUN adduser -D -u 120002 -h /opt/app app \
    && mkdir .ssh \
    && mkdir ../tasks_yaml \
    && echo "StrictHostKeyChecking=no" > .ssh/config \
    && sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories \
    && apk add gcc g++ make libffi-dev openssl-dev tzdata openssh-client sshpass \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ pipenv pywinrm ansible \
    && pipenv lock \
    && pipenv install --system --deploy \
    && apk del gcc g++ make libffi-dev openssl-dev tzdata \
    && rm -rf /var/cache/apk/*
RUN chown -R app:app /opt/app
USER app
CMD ["python", "-u", "main.py"]