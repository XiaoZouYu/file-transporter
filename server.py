import asyncio
import struct
import json
import os
import io
import zipfile
import argparse
import logging

STORAGE_PATH = "./"

HOST, PORT = "127.0.0.1", 8888


class StatusCode:
    PROTOCOL_CODES = {
        "ok": struct.pack('i', 200),
        "file_exists": struct.pack('i', 409),
        "not_found": struct.pack('i', 404),
        "bad_request": struct.pack('i', 400),
    }

    def __init__(self, callback):
        self.callback = callback

    async def ok(self):
        await self.callback.send(self.PROTOCOL_CODES['ok'])

    async def file_exists(self):
        await self.callback.send(self.PROTOCOL_CODES['file_exists'])

    async def not_found(self):
        await self.callback.send(self.PROTOCOL_CODES['not_found'])

    async def bad_request(self):
        await self.callback.send(self.PROTOCOL_CODES['bad_request'])


class FileHandler:

    def __init__(self, callback):
        self.callback = callback

    async def read(self, filename):
        if os.path.isfile(filename):
            with open(filename, 'rb') as file:
                compressed_content = file.read()
                header = {
                    "filename": os.path.basename(filename),
                    "filesize": len(compressed_content)
                }
        else:
            compressed_data = io.BytesIO()
            with zipfile.ZipFile(file=compressed_data, mode='w', compression=zipfile.ZIP_DEFLATED) as zip_file:
                for root, _, files in os.walk(filename):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zip_file.write(file_path, os.path.relpath(file_path, filename))

            compressed_data.seek(0)
            compressed_content = compressed_data.read()
            header = {"filename": os.path.basename(filename) + '.zip', "filesize": compressed_data.getbuffer().nbytes}

        header_data = json.dumps(header)
        await self.callback.send(struct.pack('i', len(header_data)))
        await self.callback.send(header_data.encode())
        await self.callback.send(compressed_content)

    async def save_file(self, protocol):
        filename = os.path.join(STORAGE_PATH, protocol["filename"])

        async def handle_data():
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            logging.info(f"开始上传文件 {filename}")
            with open(filename, 'wb') as file:
                filesize = int(protocol["filesize"])
                while filesize > 0:
                    data = await self.callback.reader.read(min(filesize, 2 ** 16))
                    file.write(data)
                    filesize -= len(data)

        if os.path.exists(filename):
            await self.callback.code.file_exists()
        else:
            await self.callback.code.ok()
            await handle_data()

    async def read_file(self, protocol):
        filename = protocol["filename"]
        filename = os.path.join(STORAGE_PATH, filename)
        if not os.path.exists(filename):
            await self.callback.code.not_found()
        else:
            await self.callback.code.ok()
            logging.info(f"开始下载文件 {filename}")
            await self.read(filename)


class ScriptListener:

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.file_handler = FileHandler(self)
        self.code = StatusCode(self)

    async def send(self, msg):
        if not self.writer.is_closing():
            self.writer.write(msg)
            await self.writer.drain()

    async def head(self):
        head_len = await self.reader.read(4)
        head_len_value = struct.unpack('i', head_len)[0]
        head_struct = await self.reader.read(head_len_value)
        return head_struct.decode()

    async def option(self):
        return await self.head()

    async def upload(self):
        while True:
            head_struct = await self.head()
            if head_struct == "over":
                break
            protocol = json.loads(head_struct)
            await self.file_handler.save_file(protocol)

    async def download(self):
        protocol = json.loads(await self.head())
        await self.file_handler.read_file(protocol)


# 服务器的回调函数
async def script_handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    logging.info(f"{writer.get_extra_info('peername')} 连接成功！")
    handle = ScriptListener(reader, writer)
    option = await handle.option()
    if option == "upload":
        await handle.code.ok()
        await handle.upload()
    elif option == 'download':
        await handle.code.ok()
        await handle.download()
    else:
        await handle.code.not_found()

    writer.close()
    await writer.wait_closed()


# 主函数
async def main():
    server = await asyncio.start_server(script_handle, host=HOST, port=PORT)
    addr = server.sockets[0].getsockname()
    logging.info(f'服务开始运行 {addr} 👌')
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser()
    parser.add_argument("-S", "--storage", help="存储地址", default=STORAGE_PATH, type=str, dest="storage")
    parser.add_argument("-H", "--host", help="ip地址", default=HOST, type=str, dest="host")
    parser.add_argument("-P", "--port", help="ip端口", default=PORT, type=int, dest="port")
    args = parser.parse_args()
    PORT = args.port
    HOST = args.host
    STORAGE_PATH = args.storage

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.warning("服务停止🤚")
