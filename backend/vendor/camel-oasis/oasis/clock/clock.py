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
from datetime import datetime


class Clock:
    r"""Clock used for the sandbox."""

    def __init__(self, k: int = 1):
        self.real_start_time = datetime.now()
        self.k = k
        self.time_step = 0

    def time_transfer(self, now_time: datetime,
                      start_time: datetime) -> datetime:
        time_diff = now_time - self.real_start_time
        adjusted_diff = self.k * time_diff
        adjusted_time = start_time + adjusted_diff
        return adjusted_time

    def get_time_step(self) -> str:
        return str(self.time_step)
