# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
import asyncio
import uuid


class AsyncSafeDict:

    def __init__(self):
        self.dict = {}
        self.lock = asyncio.Lock()

    async def put(self, key, value):
        async with self.lock:
            self.dict[key] = value

    async def get(self, key, default=None):
        async with self.lock:
            return self.dict.get(key, default)

    async def pop(self, key, default=None):
        async with self.lock:
            return self.dict.pop(key, default)

    async def keys(self):
        async with self.lock:
            return list(self.dict.keys())


class Channel:

    def __init__(self):
        self.receive_queue = asyncio.Queue()  # Used to store received messages
        # Using an asynchronous safe dictionary to store messages to be sent
        self.send_dict = AsyncSafeDict()

    async def receive_from(self):
        message = await self.receive_queue.get()
        return message

    async def send_to(self, message):
        # message_id is the first element of the message
        message_id = message[0]
        await self.send_dict.put(message_id, message)

    async def write_to_receive_queue(self, action_info):
        message_id = str(uuid.uuid4())
        await self.receive_queue.put((message_id, action_info))
        return message_id

    async def read_from_send_queue(self, message_id):
        while True:
            if message_id in await self.send_dict.keys():
                # Attempting to retrieve the message
                message = await self.send_dict.pop(message_id, None)
                if message:
                    return message  # Return the found message
            # Temporarily suspend to avoid tight looping
            await asyncio.sleep(
                0.1)  # set a large one to reduce the workload of cpu
