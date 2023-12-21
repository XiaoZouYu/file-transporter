import argparse
import logging
import asyncio
import os
import json
import struct
import time


STORAGE_PATH = "./"

HOST, PORT = "127.0.0.1", 8888


class SocketListener:
    _host = HOST
    _port = PORT

    def __init__(self, host=None, port=None):
        if host:
            self._host = host
        if port:
            self._port = port

    async def send(self, msg: str):
        self.writer.write(struct.pack('i', len(msg)))
        await self.writer.drain()
        self.writer.write(msg.encode())
        await self.writer.drain()

    async def send_content(self, content):
        self.writer.write(content)
        await self.writer.drain()

    async def read_status(self):
        r = await self.reader.read(4)
        return struct.unpack('i', r)[0]

    async def read_struct(self):
        head_len = await self.reader.read(4)
        head_len_value = struct.unpack('i', head_len)[0]
        head_struct = await self.reader.read(head_len_value)
        head_struct = json.loads(head_struct.decode())
        return head_struct

    async def __aenter__(self):
        self.reader, self.writer = await asyncio.open_connection(self._host, self._port)
        logging.info(f"{self._host}:{self._port} 连接成功！")
        return self

    async def __aexit__(self, *args):
        await self.writer.drain()
        self.writer.close()
        await self.writer.wait_closed()
        logging.info(f"{self._host}:{self._port} 关闭成功！")


class FinderCallback:

    async def upload(self, root_path, file_paths):
        async with SocketListener() as socket:
            await socket.send("upload")
            if await socket.read_status() != 200:
                logging.info("无法上传！")

            for file_path in file_paths:
                with open(file_path, 'rb') as file:
                    content = file.read()
                    head_struct = {
                        "filename": os.path.relpath(file_path, root_path),
                        "filesize": len(content)
                    }

                header = json.dumps(head_struct)
                await socket.send(header)

                rid = await socket.read_status()
                if rid == 200:
                    logging.info(f"{file_path} 开始上传！")
                    # 发送文件内容
                    await socket.send_content(content)
                elif rid == 409:
                    logging.info(f"{file_path} 服务端已存在！")
            await socket.send("over")

    async def download(self, filename):
        async with SocketListener() as socket:
            await socket.send("download")

            r = await socket.read_status()
            if r != 200:
                logging.info("不允许下载！")
                return

            header = json.dumps({"filename": filename})
            await socket.send(header)

            rid = await socket.read_status()
            if rid == 404:
                logging.info(f"{filename} 文件不存在！")
                return
            if rid == 200:
                head_struct = await socket.read_struct()

                file_path = os.path.join(STORAGE_PATH, head_struct["filename"])
                logging.info(f"{filename} 开始下载、存储目录 {file_path}")
                with open(file_path, 'wb') as file:
                    filesize = int(head_struct["filesize"])
                    while filesize > 0:
                        data = await socket.reader.read(min(filesize, 2 ** 16))
                        file.write(data)
                        filesize -= len(data)

                logging.info(f"{filename} 下载完成！")


class FileFinder:

    def __init__(self, callback=None):
        self.callback = callback or FinderCallback()

    def list_files(self, file_dir):
        if os.path.isfile(file_dir):
            yield file_dir
        else:
            for p in os.listdir(file_dir):
                yield from self.list_files(os.path.join(file_dir, p))

    async def upload_file(self, file_path):
        await self.callback.upload(os.path.dirname(file_path), self.list_files(file_path))

    async def download_file(self, filename):
        await self.callback.download(filename)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser()
    parser.add_argument("-S", "--storage", help="存储地址", default=STORAGE_PATH, type=str, dest="storage")
    parser.add_argument("-H", "--host", help="ip地址", default=HOST, type=str, dest="host")
    parser.add_argument("-P", "--port", help="ip端口", default=PORT, type=int, dest="port")
    parser.add_argument("-U", "--upload", help="上传文件", default=None, type=str, dest="upload")
    parser.add_argument("-D", "--download", help="下载文件", default=None, type=str, dest="download")
    args = parser.parse_args()
    PORT = args.port
    HOST = args.host
    STORAGE_PATH = args.storage

    start_time = time.time()

    f = FileFinder()
    if args.upload:
        asyncio.run(f.upload_file(args.upload))

    if args.download:
        asyncio.run(f.download_file(args.download))

    end_time = time.time()
    logging.info(f"共耗时: {end_time - start_time}s")
