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
from __future__ import annotations

import inspect
import logging
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Union

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import BaseModelBackend, ModelManager
from camel.prompts import TextPrompt
from camel.toolkits import FunctionTool
from camel.types import OpenAIBackendRole

from oasis.social_agent.agent_action import SocialAction
from oasis.social_agent.agent_environment import SocialEnvironment
from oasis.social_platform import Channel
from oasis.social_platform.config import UserInfo
from oasis.social_platform.typing import ActionType

if TYPE_CHECKING:
    from oasis.social_agent import AgentGraph

if "sphinx" not in sys.modules:
    agent_log = logging.getLogger(name="social.agent")
    agent_log.setLevel("DEBUG")

    if not agent_log.handlers:
        now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_handler = logging.FileHandler(
            f"./log/social.agent-{str(now)}.log")
        file_handler.setLevel("DEBUG")
        file_handler.setFormatter(
            logging.Formatter(
                "%(levelname)s - %(asctime)s - %(name)s - %(message)s"))
        agent_log.addHandler(file_handler)

ALL_SOCIAL_ACTIONS = [action.value for action in ActionType]


class SocialAgent(ChatAgent):
    r"""Social Agent."""

    def __init__(self,
                 agent_id: int,
                 user_info: UserInfo,
                 user_info_template: TextPrompt | None = None,
                 channel: Channel | None = None,
                 model: Optional[Union[BaseModelBackend,
                                       List[BaseModelBackend],
                                       ModelManager]] = None,
                 agent_graph: "AgentGraph" = None,
                 available_actions: list[ActionType] = None,
                 tools: Optional[List[Union[FunctionTool, Callable]]] = None,
                 max_iteration: int = 1,
                 interview_record: bool = False):
        self.social_agent_id = agent_id
        self.user_info = user_info
        self.channel = channel or Channel()
        self.env = SocialEnvironment(SocialAction(agent_id, self.channel))
        if user_info_template is None:
            system_message_content = self.user_info.to_system_message()
        else:
            system_message_content = self.user_info.to_custom_system_message(
                user_info_template)
        system_message = BaseMessage.make_assistant_message(
            role_name="system",
            content=system_message_content,  # system prompt
        )

        if not available_actions:
            agent_log.info("No available actions defined, using all actions.")
            self.action_tools = self.env.action.get_openai_function_list()
        else:
            all_tools = self.env.action.get_openai_function_list()
            all_possible_actions = [tool.func.__name__ for tool in all_tools]

            for action in available_actions:
                action_name = action.value if isinstance(
                    action, ActionType) else action
                if action_name not in all_possible_actions:
                    agent_log.warning(
                        f"Action {action_name} is not supported. Supported "
                        f"actions are: {', '.join(all_possible_actions)}")
            self.action_tools = [
                tool for tool in all_tools if tool.func.__name__ in [
                    a.value if isinstance(a, ActionType) else a
                    for a in available_actions
                ]
            ]
        all_tools = (tools or []) + (self.action_tools or [])
        super().__init__(
            system_message=system_message,
            model=model,
            scheduling_strategy='random_model',
            tools=all_tools,
        )
        self.max_iteration = max_iteration
        self.interview_record = interview_record
        self.agent_graph = agent_graph
        self.test_prompt = (
            "\n"
            "Helen is a successful writer who usually writes popular western "
            "novels. Now, she has an idea for a new novel that could really "
            "make a big impact. If it works out, it could greatly "
            "improve her career. But if it fails, she will have spent "
            "a lot of time and effort for nothing.\n"
            "\n"
            "What do you think Helen should do?")

    async def perform_action_by_llm(self):
        # Get posts:
        env_prompt = await self.env.to_text_prompt()
        user_msg = BaseMessage.make_user_message(
            role_name="User",
            content=(
                f"Please perform social media actions after observing the "
                f"platform environments. Notice that don't limit your "
                f"actions for example to just like the posts. "
                f"Here is your social media environment: {env_prompt}"))
        try:
            agent_log.info(
                f"Agent {self.social_agent_id} observing environment: "
                f"{env_prompt}")
            response = await self.astep(user_msg)
            for tool_call in response.info['tool_calls']:
                action_name = tool_call.tool_name
                args = tool_call.args
                agent_log.info(f"Agent {self.social_agent_id} performed "
                               f"action: {action_name} with args: {args}")
                if action_name not in ALL_SOCIAL_ACTIONS:
                    agent_log.info(
                        f"Agent {self.social_agent_id} get the result: "
                        f"{tool_call.result}")
                # Abort graph action for if 100w Agent
                # self.perform_agent_graph_action(action_name, args)

                return response
        except Exception as e:
            agent_log.error(f"Agent {self.social_agent_id} error: {e}")
            return e

    async def perform_test(self):
        """
        doing group polarization test for all agents.
        TODO: rewrite the function according to the ChatAgent.
        TODO: unify the test and interview function.
        """
        # user conduct test to agent
        _ = BaseMessage.make_user_message(role_name="User",
                                          content=("You are a twitter user."))
        # Test memory should not be writed to memory.
        # self.memory.write_record(MemoryRecord(user_msg,
        #                                       OpenAIBackendRole.USER))

        openai_messages, num_tokens = self.memory.get_context()

        openai_messages = ([{
            "role":
            self.system_message.role_name,
            "content":
            self.system_message.content.split("# RESPONSE FORMAT")[0],
        }] + openai_messages + [{
            "role": "user",
            "content": self.test_prompt
        }])

        agent_log.info(f"Agent {self.social_agent_id}: {openai_messages}")
        # NOTE: this is a temporary solution.
        # Camel can not stop updating the agents' memory after stop and astep
        # now.
        response = await self._aget_model_response(
            openai_messages=openai_messages, num_tokens=num_tokens)
        content = response.output_messages[0].content
        agent_log.info(
            f"Agent {self.social_agent_id} receive response: {content}")
        return {
            "user_id": self.social_agent_id,
            "prompt": openai_messages,
            "content": content
        }

    async def perform_interview(self, interview_prompt: str):
        """
        Perform an interview with the agent.
        """
        # user conduct test to agent
        user_msg = BaseMessage.make_user_message(
            role_name="User", content=("You are a twitter user."))

        if self.interview_record:
            # Test memory should not be writed to memory.
            self.update_memory(message=user_msg, role=OpenAIBackendRole.SYSTEM)

        openai_messages, num_tokens = self.memory.get_context()

        openai_messages = ([{
            "role":
            self.system_message.role_name,
            "content":
            self.system_message.content.split("# RESPONSE FORMAT")[0],
        }] + openai_messages + [{
            "role": "user",
            "content": interview_prompt
        }])

        agent_log.info(f"Agent {self.social_agent_id}: {openai_messages}")
        # NOTE: this is a temporary solution.
        # Camel can not stop updating the agents' memory after stop and astep
        # now.

        response = await self._aget_model_response(
            openai_messages=openai_messages, num_tokens=num_tokens)

        content = response.output_messages[0].content

        if self.interview_record:
            # Test memory should not be writed to memory.
            self.update_memory(message=response.output_messages[0],
                               role=OpenAIBackendRole.USER)
        agent_log.info(
            f"Agent {self.social_agent_id} receive response: {content}")

        # Record the complete interview (prompt + response) through the channel
        interview_data = {"prompt": interview_prompt, "response": content}
        result = await self.env.action.perform_action(
            interview_data, ActionType.INTERVIEW.value)

        # Return the combined result
        return {
            "user_id": self.social_agent_id,
            "prompt": openai_messages,
            "content": content,
            "success": result.get("success", False)
        }

    async def perform_action_by_hci(self) -> Any:
        print("Please choose one function to perform:")
        function_list = self.env.action.get_openai_function_list()
        for i in range(len(function_list)):
            agent_log.info(f"Agent {self.social_agent_id} function: "
                           f"{function_list[i].func.__name__}")

        selection = int(input("Enter your choice: "))
        if not 0 <= selection < len(function_list):
            agent_log.error(f"Agent {self.social_agent_id} invalid input.")
            return
        func = function_list[selection].func

        params = inspect.signature(func).parameters
        args = []
        for param in params.values():
            while True:
                try:
                    value = input(f"Enter value for {param.name}: ")
                    args.append(value)
                    break
                except ValueError:
                    agent_log.error("Invalid input, please enter an integer.")

        result = await func(*args)
        return result

    async def perform_action_by_data(self, func_name, *args, **kwargs) -> Any:
        func_name = func_name.value if isinstance(func_name,
                                                  ActionType) else func_name
        function_list = self.env.action.get_openai_function_list()
        for i in range(len(function_list)):
            if function_list[i].func.__name__ == func_name:
                func = function_list[i].func
                result = await func(*args, **kwargs)
                self.update_memory(message=BaseMessage.make_user_message(
                    role_name=OpenAIBackendRole.SYSTEM,
                    content=f"Agent {self.social_agent_id} performed "
                    f"{func_name} with args: {args} and kwargs: {kwargs}"
                    f"and the result is {result}"),
                                   role=OpenAIBackendRole.SYSTEM)
                agent_log.info(f"Agent {self.social_agent_id}: {result}")
                return result
        raise ValueError(f"Function {func_name} not found in the list.")

    def perform_agent_graph_action(
        self,
        action_name: str,
        arguments: dict[str, Any],
    ):
        r"""Remove edge if action is unfollow or add edge
        if action is follow to the agent graph.
        """
        if "unfollow" in action_name:
            followee_id: int | None = arguments.get("followee_id", None)
            if followee_id is None:
                return
            self.agent_graph.remove_edge(self.social_agent_id, followee_id)
            agent_log.info(
                f"Agent {self.social_agent_id} unfollowed Agent {followee_id}")
        elif "follow" in action_name:
            followee_id: int | None = arguments.get("followee_id", None)
            if followee_id is None:
                return
            self.agent_graph.add_edge(self.social_agent_id, followee_id)
            agent_log.info(
                f"Agent {self.social_agent_id} followed Agent {followee_id}")

    def __str__(self) -> str:
        return (f"{self.__class__.__name__}(agent_id={self.social_agent_id}, "
                f"model_type={self.model_type.value})")
