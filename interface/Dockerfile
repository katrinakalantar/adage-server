FROM adage-server/docker-interface-base

# Copy code to server directory
COPY . /home/user/

RUN grunt

CMD mv bin compile_folder && mv build compile_folder
