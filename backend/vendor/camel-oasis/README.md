<div align="center">
  <a href="https://www.camel-ai.org/">
    <img src="assets/banner.png" alt=banner>
  </a>
</div>

</br>

<div align="center">

<h1> OASIS: Open Agent Social Interaction Simulations with One Million Agents
</h1>

[![Documentation][docs-image]][docs-url]
[![Discord][discord-image]][discord-url]
[![X][x-image]][x-url]
[![Reddit][reddit-image]][reddit-url]
[![Wechat][wechat-image]][wechat-url]
[![Wechat][oasis-image]][oasis-url]
[![Hugging Face][huggingface-image]][huggingface-url]
[![Star][star-image]][star-url]
[![Package License][package-license-image]][package-license-url]

<h4 align="center">

[Community](https://github.com/camel-ai/camel#community) |
[Paper](https://arxiv.org/abs/2411.11581) |
[Examples](https://github.com/camel-ai/oasis/tree/main/scripts) |
[Dataset](https://huggingface.co/datasets/echo-yiyiyi/oasis-dataset) |
[Citation](https://github.com/camel-ai/oasis#-citation) |
[Contributing](https://github.com/camel-ai/oasis#-contributing-to-oasis) |
[CAMEL-AI](https://www.camel-ai.org/)

</h4>

</div>

<br>

<p align="left">
  <img src='assets/intro.png'>

🏝️ OASIS is a scalable, open-source social media simulator that incorporates large language model agents to realistically mimic the behavior of up to one million users on platforms like Twitter and Reddit. It's designed to facilitate the study of complex social phenomena such as information spread, group polarization, and herd behavior, offering a versatile tool for exploring diverse social dynamics and user interactions in digital environments.

</p>

<br>

<div align="center">
🌟 Star OASIS on GitHub and be instantly notified of new releases.
</div>

<br>

<div align="center">
    <img src="assets/star.gif" alt="Star" width="196" height="52">
  </a>
</div>

<br>

## ✨ Key Features

### 📈 Scalability

OASIS supports simulations of up to ***one million agents***, enabling studies of social media dynamics at a scale comparable to real-world platforms.

### 📲 Dynamic Environments

Adapts to real-time changes in social networks and content, mirroring the fluid dynamics of platforms like **Twitter** and **Reddit** for authentic simulation experiences.

### 👍🏼 Diverse Action Spaces

Agents can perform **23 actions**, such as following, commenting, and reposting, allowing for rich, multi-faceted interactions.

### 🔥 Integrated Recommendation Systems

Features **interest-based** and **hot-score-based recommendation algorithms**, simulating how users discover content and interact within social media platforms.

<br>

## 📺 Demo Video

### Introducing OASIS: Open Agent Social Interaction Simulations with One Million Agents

https://github.com/user-attachments/assets/3bd2553c-d25d-4d8c-a739-1af51354b15a

<br>

For more showcaes:

- Can 1,000,000 AI agents simulate social media?
  [→Watch demo](https://www.youtube.com/watch?v=lprGHqkApus&t=2s)

<br>

## 🎯 Usecase

<div align="left">
    <img src="assets/research_simulation.png" alt=usecase1>
    <img src="assets/interaction.png" alt=usecase2>
   <a href="http://www.matrix.eigent.ai">
    <img src="assets/content_creation.png" alt=usecase3>
   </a>
    <img src="assets/prediction.png" alt=usecase4>
</div>

## ⚙️ Quick Start

1. **Install the OASIS package:**

Installing OASIS is a breeze thanks to its availability on PyPI. Simply open your terminal and run:

```bash
pip install camel-oasis
```

2. **Set up your OpenAI API key:**

```bash
# For Bash shell (Linux, macOS, Git Bash on Windows):
export OPENAI_API_KEY=<insert your OpenAI API key>

# For Windows Command Prompt:
set OPENAI_API_KEY=<insert your OpenAI API key>
```

3. **Prepare the agent profile file:**

Create the profile you want to assign to the agent. As an example, you can download [user_data_36.json](https://github.com/camel-ai/oasis/blob/main/data/reddit/user_data_36.json) and place it in your local `./data/reddit` folder.

4. **Run the following Python code:**

```python
import asyncio
import os

from camel.models import ModelFactory
from camel.types import ModelPlatformType, ModelType

import oasis
from oasis import (ActionType, LLMAction, ManualAction,
                   generate_reddit_agent_graph)


async def main():
    # Define the model for the agents
    openai_model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=ModelType.GPT_4O_MINI,
    )

    # Define the available actions for the agents
    available_actions = [
        ActionType.LIKE_POST,
        ActionType.DISLIKE_POST,
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.LIKE_COMMENT,
        ActionType.DISLIKE_COMMENT,
        ActionType.SEARCH_POSTS,
        ActionType.SEARCH_USER,
        ActionType.TREND,
        ActionType.REFRESH,
        ActionType.DO_NOTHING,
        ActionType.FOLLOW,
        ActionType.MUTE,
    ]

    agent_graph = await generate_reddit_agent_graph(
        profile_path="./data/reddit/user_data_36.json",
        model=openai_model,
        available_actions=available_actions,
    )

    # Define the path to the database
    db_path = "./data/reddit_simulation.db"

    # Delete the old database
    if os.path.exists(db_path):
        os.remove(db_path)

    # Make the environment
    env = oasis.make(
        agent_graph=agent_graph,
        platform=oasis.DefaultPlatformType.REDDIT,
        database_path=db_path,
    )

    # Run the environment
    await env.reset()

    actions_1 = {}
    actions_1[env.agent_graph.get_agent(0)] = [
        ManualAction(action_type=ActionType.CREATE_POST,
                     action_args={"content": "Hello, world!"}),
        ManualAction(action_type=ActionType.CREATE_COMMENT,
                     action_args={
                         "post_id": "1",
                         "content": "Welcome to the OASIS World!"
                     })
    ]
    actions_1[env.agent_graph.get_agent(1)] = ManualAction(
        action_type=ActionType.CREATE_COMMENT,
        action_args={
            "post_id": "1",
            "content": "I like the OASIS world."
        })
    await env.step(actions_1)

    actions_2 = {
        agent: LLMAction()
        for _, agent in env.agent_graph.get_agents()
    }

    # Perform the actions
    await env.step(actions_2)

    # Close the environment
    await env.close()


if __name__ == "__main__":
    asyncio.run(main())
```

<br>

> \[!TIP\]
> For more detailed instructions and additional configuration options, check out the [documentation](https://docs.oasis.camel-ai.org/).

### More Tutorials

To discover how to create profiles for large-scale users, as well as how to visualize and analyze social simulation data once your experiment concludes, please refer to [More Tutorials](examples/experiment/user_generation_visualization.md) for detailed guidance.

<div align="center">
  <img src="assets/tutorial.png" alt="Tutorial Overview">
</div>

## 📢 News

### Upcoming Features & Contributions

> We welcome community contributions! Join us in building these exciting features.

- [Support Multi Modal Platform](https://github.com/camel-ai/oasis/issues/47)

<!-- - Public release of our dataset on Hugging Face (November 05, 2024) -->

### Latest Updates

📢 Update the camel-ai version to 0.2.78 and update the dataset HuggingFace link.  - 📆 December 4, 2025

- Add the report post action to mark inappropriate content. - 📆 June 8, 2025
- Add features for creating group chats, sending messages in group chats, and leaving group chats. - 📆 June 6, 2025
- Support Interview Action for asking agents specific questions and getting answers. - 📆 June 2, 2025
- Support customization of each agent's models, tools, and prompts; refactor the interface to follow the PettingZoo style. - 📆 May 22, 2025
- Refactor into the OASIS environment, publish camel-oasis on PyPI, and release the documentation. - 📆 April 24, 2025
- Support OPENAI Embedding model for Twhin-Bert Recommendation System. - 📆 March 25, 2025
  ...
- Slightly refactoring the database to add Quote Action and modify Repost Action - 📆 January 13, 2025
- Added the demo video and oasis's star history in the README - 📆 January 5, 2025
- Introduced an Electronic Mall on the Reddit platform - 📆 December 5, 2024
- OASIS initially released on arXiv - 📆 November 19, 2024
- OASIS GitHub repository initially launched - 📆 November 19, 2024

## 🔎 Follow-up Research

- [MultiAgent4Collusion](https://github.com/renqibing/MultiAgent4Collusion): multi-agent collusion simulation framework in social systems
- More to come...

If your research is based on OASIS, we'd be happy to feature your work here—feel free to reach out or submit a pull request to add it to the [README](https://github.com/camel-ai/oasis/blob/main/README.md)!

## 🥂 Contributing to OASIS🏝️

> We greatly appreciate your interest in contributing to our open-source initiative. To ensure a smooth collaboration and the success of contributions, we adhere to a set of contributing guidelines similar to those established by CAMEL. For a comprehensive understanding of the steps involved in contributing to our project, please refer to the OASIS [contributing guidelines](https://github.com/camel-ai/oasis/blob/master/CONTRIBUTING.md). 🤝🚀
>
> An essential part of contributing involves not only submitting new features with accompanying tests (and, ideally, examples) but also ensuring that these contributions pass our automated pytest suite. This approach helps us maintain the project's quality and reliability by verifying compatibility and functionality.

## 📬 Community & Contact

If you're keen on exploring new research opportunities or discoveries with our platform and wish to dive deeper or suggest new features, we're here to talk. Feel free to get in touch for more details at camel.ai.team@gmail.com.

<br>

- Join us ([*Discord*](https://discord.camel-ai.org/) or [*WeChat*](https://ghli.org/camel/wechat.png)) in pushing the boundaries of finding the scaling laws of agents.

- Join WechatGroup for further discussions!

<div align="">
  <img src="assets/wechatgroup.png" alt="WeChat Group QR Code" width="600">
</div>

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=camel-ai/oasis&type=Date)](https://star-history.com/#camel-ai/oasis&Date)

## 🔗 Citation

```
@misc{yang2024oasisopenagentsocial,
      title={OASIS: Open Agent Social Interaction Simulations with One Million Agents},
      author={Ziyi Yang and Zaibin Zhang and Zirui Zheng and Yuxian Jiang and Ziyue Gan and Zhiyu Wang and Zijian Ling and Jinsong Chen and Martz Ma and Bowen Dong and Prateek Gupta and Shuyue Hu and Zhenfei Yin and Guohao Li and Xu Jia and Lijun Wang and Bernard Ghanem and Huchuan Lu and Chaochao Lu and Wanli Ouyang and Yu Qiao and Philip Torr and Jing Shao},
      year={2024},
      eprint={2411.11581},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2411.11581},
}
```

## 🙌 Acknowledgment

We would like to thank Douglas for designing the logo of our project.

## 🖺 License

The source code is licensed under Apache 2.0.

[discord-image]: https://img.shields.io/discord/1082486657678311454?logo=discord&labelColor=%20%235462eb&logoColor=%20%23f5f5f5&color=%20%235462eb
[discord-url]: https://discord.camel-ai.org/
[docs-image]: https://img.shields.io/badge/Documentation-EB3ECC
[docs-url]: https://docs.oasis.camel-ai.org/
[huggingface-image]: https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-CAMEL--AI-ffc107?color=ffc107&logoColor=white
[huggingface-url]: https://huggingface.co/camel-ai
[oasis-image]: https://img.shields.io/badge/WeChat-OASISProject-brightgreen?logo=wechat&logoColor=white
[oasis-url]: ./assets/wechatgroup.png
[package-license-image]: https://img.shields.io/badge/License-Apache_2.0-blue.svg
[package-license-url]: https://github.com/camel-ai/oasis/blob/main/licenses/LICENSE
[reddit-image]: https://img.shields.io/reddit/subreddit-subscribers/CamelAI?style=plastic&logo=reddit&label=r%2FCAMEL&labelColor=white
[reddit-url]: https://www.reddit.com/r/CamelAI/
[star-image]: https://img.shields.io/github/stars/camel-ai/oasis?label=stars&logo=github&color=brightgreen
[star-url]: https://github.com/camel-ai/oasis/stargazers
[wechat-image]: https://img.shields.io/badge/WeChat-CamelAIOrg-brightgreen?logo=wechat&logoColor=white
[wechat-url]: ./assets/wechat.JPGwechat.jpg
[x-image]: https://img.shields.io/twitter/follow/CamelAIOrg?style=social
[x-url]: https://x.com/CamelAIOrg
