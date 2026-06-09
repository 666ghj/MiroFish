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

import asyncio
import logging
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Any

from oasis.clock.clock import Clock
from oasis.social_platform.channel import Channel
from oasis.social_platform.database import (create_db,
                                            fetch_rec_table_as_matrix,
                                            fetch_table_from_db)
from oasis.social_platform.platform_utils import PlatformUtils
from oasis.social_platform.recsys import (rec_sys_personalized_twh,
                                          rec_sys_personalized_with_trace,
                                          rec_sys_random, rec_sys_reddit)
from oasis.social_platform.typing import ActionType, RecsysType

# Create log directory if it doesn't exist
log_dir = "./log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

if "sphinx" not in sys.modules:
    twitter_log = logging.getLogger(name="social.twitter")
    twitter_log.setLevel("DEBUG")
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_handler = logging.FileHandler(f"./log/social.twitter-{now}.log")
    file_handler.setLevel("DEBUG")
    file_handler.setFormatter(
        logging.Formatter(
            "%(levelname)s - %(asctime)s - %(name)s - %(message)s"))
    twitter_log.addHandler(file_handler)


class Platform:
    r"""Platform."""

    def __init__(
        self,
        db_path: str,
        channel: Any = None,
        sandbox_clock: Clock | None = None,
        start_time: datetime | None = None,
        show_score: bool = False,
        allow_self_rating: bool = True,
        recsys_type: str | RecsysType = "reddit",
        refresh_rec_post_count: int = 1,
        max_rec_post_len: int = 2,
        following_post_count=3,
        use_openai_embedding: bool = False,
    ):
        self.db_path = db_path
        self.recsys_type = recsys_type
        # import pdb; pdb.set_trace()

        # If no clock is specified, default the platform's time
        # magnification factor to 60
        if sandbox_clock is None:
            sandbox_clock = Clock(60)
        if start_time is None:
            start_time = datetime.now()
        self.start_time = start_time
        self.sandbox_clock = sandbox_clock

        self.db, self.db_cursor = create_db(self.db_path)
        self.db.execute("PRAGMA synchronous = OFF")

        self.channel = channel or Channel()

        self.recsys_type = RecsysType(recsys_type)

        # Whether to simulate showing scores like Reddit (likes minus dislikes)
        # instead of showing likes and dislikes separately
        self.show_score = show_score

        # Whether to allow users to like or dislike their own posts and
        # comments
        self.allow_self_rating = allow_self_rating

        # The number of posts returned by the social media internal
        # recommendation system per refresh
        self.refresh_rec_post_count = refresh_rec_post_count
        # The number of posts returned at once from posts made by followed
        # users, ranked by like counts
        self.following_post_count = following_post_count
        # The maximum number of posts per user in the recommendation
        # table (buffer)
        self.max_rec_post_len = max_rec_post_len
        # rec prob between random and personalized
        self.rec_prob = 0.7
        self.use_openai_embedding = use_openai_embedding

        # Parameters for the platform's internal trending rules
        self.trend_num_days = 7
        self.trend_top_k = 1

        # Report threshold setting
        self.report_threshold = 2

        self.pl_utils = PlatformUtils(
            self.db,
            self.db_cursor,
            self.start_time,
            self.sandbox_clock,
            self.show_score,
            self.recsys_type,
            self.report_threshold,
        )

    async def running(self):
        while True:
            message_id, data = await self.channel.receive_from()

            agent_id, message, action = data
            action = ActionType(action)

            if action == ActionType.EXIT:
                # If the database is in-memory, save it to a file before
                # losing
                if self.db_path == ":memory:":
                    dst = sqlite3.connect("mock.db")
                    with dst:
                        self.db.backup(dst)

                self.db_cursor.close()
                self.db.close()
                break

            # Retrieve the corresponding function using getattr
            action_function = getattr(self, action.value, None)
            if action_function:
                # Get the names of the parameters of the function
                func_code = action_function.__code__
                param_names = func_code.co_varnames[:func_code.co_argcount]

                len_param_names = len(param_names)
                if len_param_names > 3:
                    raise ValueError(
                        f"Functions with {len_param_names} parameters are not "
                        f"supported.")
                # Build a dictionary of parameters
                params = {}
                if len_param_names >= 2:
                    params["agent_id"] = agent_id
                if len_param_names == 3:
                    # Assuming the second element in param_names is the name
                    # of the second parameter you want to add
                    second_param_name = param_names[2]
                    params[second_param_name] = message

                # Call the function with the parameters
                result = await action_function(**params)
                await self.channel.send_to((message_id, agent_id, result))
            else:
                raise ValueError(f"Action {action} is not supported")

    def run(self):
        asyncio.run(self.running())

    async def sign_up(self, agent_id, user_message):
        user_name, name, bio = user_message
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_insert_query = (
                "INSERT INTO user (user_id, agent_id, user_name, name, "
                "bio, created_at, num_followings, num_followers) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?)")
            self.pl_utils._execute_db_command(
                user_insert_query,
                (agent_id, agent_id, user_name, name, bio, current_time, 0, 0),
                commit=True,
            )
            user_id = agent_id

            action_info = {"name": name, "user_name": user_name, "bio": bio}
            self.pl_utils._record_trace(user_id, ActionType.SIGNUP.value,
                                        action_info, current_time)
            # twitter_log.info(f"Trace inserted: user_id={user_id}, "
            #                  f"current_time={current_time}, "
            #                  f"action={ActionType.SIGNUP.value}, "
            #                  f"info={action_info}")
            return {"success": True, "user_id": user_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def sign_up_product(self, product_id: int, product_name: str):
        # Note: do not sign up the product with the same product name
        try:
            product_insert_query = (
                "INSERT INTO product (product_id, product_name) VALUES (?, ?)")
            self.pl_utils._execute_db_command(product_insert_query,
                                              (product_id, product_name),
                                              commit=True)
            return {"success": True, "product_id": product_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def purchase_product(self, agent_id, purchase_message):
        product_name, purchase_num = purchase_message
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        # try:
        user_id = agent_id
        # Check if a like record already exists
        product_check_query = (
            "SELECT * FROM 'product' WHERE product_name = ?")
        self.pl_utils._execute_db_command(product_check_query,
                                          (product_name, ))
        check_result = self.db_cursor.fetchone()
        if not check_result:
            # Product not found
            return {"success": False, "error": "No such product."}
        else:
            product_id = check_result[0]

        product_update_query = (
            "UPDATE product SET sales = sales + ? WHERE product_name = ?")
        self.pl_utils._execute_db_command(product_update_query,
                                          (purchase_num, product_name),
                                          commit=True)

        # Record the action in the trace table
        action_info = {
            "product_name": product_name,
            "purchase_num": purchase_num
        }
        self.pl_utils._record_trace(user_id, ActionType.PURCHASE_PRODUCT.value,
                                    action_info, current_time)
        return {"success": True, "product_id": product_id}
        # except Exception as e:
        #     return {"success": False, "error": str(e)}

    async def refresh(self, agent_id: int):
        # Retrieve posts for a specific id from the rec table
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id
            # Retrieve all post_ids for a given user_id from the rec table
            rec_query = "SELECT post_id FROM rec WHERE user_id = ?"
            self.pl_utils._execute_db_command(rec_query, (user_id, ))
            rec_results = self.db_cursor.fetchall()

            post_ids = [row[0] for row in rec_results]
            selected_post_ids = post_ids
            # If the number of post_ids >= self.refresh_rec_post_count,
            # randomly select a specified number of post_ids
            if len(selected_post_ids) >= self.refresh_rec_post_count:
                selected_post_ids = random.sample(selected_post_ids,
                                                  self.refresh_rec_post_count)

            if self.recsys_type != RecsysType.REDDIT:
                # Retrieve posts from following (in network)
                # Modify the SQL query so that the refresh gets posts from
                # people the user follows, sorted by the number of likes on
                # Twitter
                query_following_post = (
                    "SELECT post.post_id, post.user_id, post.content, "
                    "post.created_at, post.num_likes FROM post "
                    "JOIN follow ON post.user_id = follow.followee_id "
                    "WHERE follow.follower_id = ? "
                    "ORDER BY post.num_likes DESC "
                    "LIMIT ?")
                self.pl_utils._execute_db_command(
                    query_following_post,
                    (
                        user_id,
                        self.following_post_count,
                    ),
                )

                following_posts = self.db_cursor.fetchall()
                following_posts_ids = [row[0] for row in following_posts]

                selected_post_ids = following_posts_ids + selected_post_ids
                selected_post_ids = list(set(selected_post_ids))

            placeholders = ", ".join("?" for _ in selected_post_ids)

            post_query = (
                f"SELECT post_id, user_id, original_post_id, content, "
                f"quote_content, created_at, num_likes, num_dislikes, "
                f"num_shares FROM post WHERE post_id IN ({placeholders})")
            self.pl_utils._execute_db_command(post_query, selected_post_ids)
            results = self.db_cursor.fetchall()
            if not results:
                return {"success": False, "message": "No posts found."}
            results_with_comments = self.pl_utils._add_comments_to_posts(
                results)

            action_info = {"posts": results_with_comments}
            # twitter_log.info(action_info)
            self.pl_utils._record_trace(user_id, ActionType.REFRESH.value,
                                        action_info, current_time)

            return {"success": True, "posts": results_with_comments}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def update_rec_table(self):
        # Recsys(trace/user/post table), refresh rec table
        twitter_log.info("Starting to refresh recommendation system cache...")
        user_table = fetch_table_from_db(self.db_cursor, "user")
        post_table = fetch_table_from_db(self.db_cursor, "post")
        trace_table = fetch_table_from_db(self.db_cursor, "trace")
        rec_matrix = fetch_rec_table_as_matrix(self.db_cursor)

        if self.recsys_type == RecsysType.RANDOM:
            new_rec_matrix = rec_sys_random(post_table, rec_matrix,
                                            self.max_rec_post_len)
        elif self.recsys_type == RecsysType.TWITTER:
            new_rec_matrix = rec_sys_personalized_with_trace(
                user_table, post_table, trace_table, rec_matrix,
                self.max_rec_post_len)
        elif self.recsys_type == RecsysType.TWHIN:
            try:
                latest_post_time = post_table[-1]["created_at"]
                second_latest_post_time = post_table[-2]["created_at"] if len(
                    post_table) > 1 else latest_post_time
                post_query = """
                    SELECT COUNT(*)
                    FROM post
                    WHERE created_at = ? OR created_at = ?
                """
                self.pl_utils._execute_db_command(
                    post_query, (latest_post_time, second_latest_post_time))
                result = self.db_cursor.fetchone()
                latest_post_count = result[0]
                if not latest_post_count:
                    return {
                        "success": False,
                        "message": "Fail to get latest posts count"
                    }
                new_rec_matrix = rec_sys_personalized_twh(
                    user_table,
                    post_table,
                    latest_post_count,
                    trace_table,
                    rec_matrix,
                    self.max_rec_post_len,
                    self.sandbox_clock.time_step,
                    use_openai_embedding=self.use_openai_embedding,
                )
            except Exception as e:
                twitter_log.error(e)
                # If no post in the platform, skip updating the rec table
                return
        elif self.recsys_type == RecsysType.REDDIT:
            new_rec_matrix = rec_sys_reddit(post_table, rec_matrix,
                                            self.max_rec_post_len)
        else:
            raise ValueError("Unsupported recommendation system type, please "
                             "check the `RecsysType`.")

        sql_query = "DELETE FROM rec"
        # Execute the SQL statement using the _execute_db_command function
        self.pl_utils._execute_db_command(sql_query, commit=True)

        # Batch insertion is more time-efficient
        # create a list of values to insert
        insert_values = [(user_id, post_id)
                         for user_id in range(len(new_rec_matrix))
                         for post_id in new_rec_matrix[user_id]]

        # Perform batch insertion into the database
        self.pl_utils._execute_many_db_command(
            "INSERT INTO rec (user_id, post_id) VALUES (?, ?)",
            insert_values,
            commit=True,
        )

    async def create_post(self, agent_id: int, content: str):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            post_insert_query = (
                "INSERT INTO post (user_id, content, created_at, num_likes, "
                "num_dislikes, num_shares) VALUES (?, ?, ?, ?, ?, ?)")
            self.pl_utils._execute_db_command(
                post_insert_query, (user_id, content, current_time, 0, 0, 0),
                commit=True)
            post_id = self.db_cursor.lastrowid

            action_info = {"content": content, "post_id": post_id}
            self.pl_utils._record_trace(user_id, ActionType.CREATE_POST.value,
                                        action_info, current_time)

            # twitter_log.info(f"Trace inserted: user_id={user_id}, "
            #                  f"current_time={current_time}, "
            #                  f"action={ActionType.CREATE_POST.value}, "
            #                  f"info={action_info}")
            return {"success": True, "post_id": post_id}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def repost(self, agent_id: int, post_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            # Ensure the content has not been reposted by this user before
            repost_check_query = (
                "SELECT * FROM 'post' WHERE original_post_id = ? AND "
                "user_id = ?")
            self.pl_utils._execute_db_command(repost_check_query,
                                              (post_id, user_id))
            if self.db_cursor.fetchone():
                # for common and quote post, check if the post has been
                # reposted
                return {
                    "success": False,
                    "error": "Repost record already exists."
                }

            post_type_result = self.pl_utils._get_post_type(post_id)
            post_insert_query = ("INSERT INTO post (user_id, original_post_id"
                                 ", created_at) VALUES (?, ?, ?)")
            # Update num_shares for the found post
            update_shares_query = (
                "UPDATE post SET num_shares = num_shares + 1 WHERE post_id = ?"
            )

            if not post_type_result:
                return {"success": False, "error": "Post not found."}
            elif (post_type_result['type'] == 'common'
                  or post_type_result['type'] == 'quote'):
                self.pl_utils._execute_db_command(
                    post_insert_query, (user_id, post_id, current_time),
                    commit=True)
                self.pl_utils._execute_db_command(update_shares_query,
                                                  (post_id, ),
                                                  commit=True)
            elif post_type_result['type'] == 'repost':
                repost_check_query = (
                    "SELECT * FROM 'post' WHERE original_post_id = ? AND "
                    "user_id = ?")
                self.pl_utils._execute_db_command(
                    repost_check_query,
                    (post_type_result['root_post_id'], user_id))

                if self.db_cursor.fetchone():
                    # for repost post, check if the post has been reposted
                    return {
                        "success": False,
                        "error": "Repost record already exists."
                    }

                self.pl_utils._execute_db_command(
                    post_insert_query,
                    (user_id, post_type_result['root_post_id'], current_time),
                    commit=True)
                self.pl_utils._execute_db_command(
                    update_shares_query, (post_type_result['root_post_id'], ),
                    commit=True)

            new_post_id = self.db_cursor.lastrowid

            action_info = {"reposted_id": post_id, "new_post_id": new_post_id}
            self.pl_utils._record_trace(user_id, ActionType.REPOST.value,
                                        action_info, current_time)

            return {"success": True, "post_id": new_post_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def quote_post(self, agent_id: int, quote_message: tuple):
        post_id, quote_content = quote_message
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            # Allow quote a post more than once because the quote content may
            # be different

            post_query = "SELECT content FROM post WHERE post_id = ?"

            post_type_result = self.pl_utils._get_post_type(post_id)
            post_insert_query = (
                "INSERT INTO post (user_id, original_post_id, "
                "content, quote_content, created_at) VALUES (?, ?, ?, ?, ?)")
            update_shares_query = (
                "UPDATE post SET num_shares = num_shares + 1 WHERE post_id = ?"
            )

            if not post_type_result:
                return {"success": False, "error": "Post not found."}
            elif post_type_result['type'] == 'common':
                self.pl_utils._execute_db_command(post_query, (post_id, ))
                post_content = self.db_cursor.fetchone()[0]
                self.pl_utils._execute_db_command(
                    post_insert_query, (user_id, post_id, post_content,
                                        quote_content, current_time),
                    commit=True)
                self.pl_utils._execute_db_command(update_shares_query,
                                                  (post_id, ),
                                                  commit=True)
            elif (post_type_result['type'] == 'repost'
                  or post_type_result['type'] == 'quote'):
                self.pl_utils._execute_db_command(
                    post_query, (post_type_result['root_post_id'], ))
                post_content = self.db_cursor.fetchone()[0]
                self.pl_utils._execute_db_command(
                    post_insert_query,
                    (user_id, post_type_result['root_post_id'], post_content,
                     quote_content, current_time),
                    commit=True)
                self.pl_utils._execute_db_command(
                    update_shares_query, (post_type_result['root_post_id'], ),
                    commit=True)

            new_post_id = self.db_cursor.lastrowid

            action_info = {"quoted_id": post_id, "new_post_id": new_post_id}
            self.pl_utils._record_trace(user_id, ActionType.QUOTE_POST.value,
                                        action_info, current_time)

            return {"success": True, "post_id": new_post_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def like_post(self, agent_id: int, post_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            post_type_result = self.pl_utils._get_post_type(post_id)
            if post_type_result['type'] == 'repost':
                post_id = post_type_result['root_post_id']
            user_id = agent_id
            # Check if a like record already exists
            like_check_query = ("SELECT * FROM 'like' WHERE post_id = ? AND "
                                "user_id = ?")
            self.pl_utils._execute_db_command(like_check_query,
                                              (post_id, user_id))
            if self.db_cursor.fetchone():
                # Like record already exists
                return {
                    "success": False,
                    "error": "Like record already exists."
                }

            # Check if the post to be liked is self-posted
            if self.allow_self_rating is False:
                check_result = self.pl_utils._check_self_post_rating(
                    post_id, user_id)
                if check_result:
                    return check_result

            # Update the number of likes in the post table
            post_update_query = (
                "UPDATE post SET num_likes = num_likes + 1 WHERE post_id = ?")
            self.pl_utils._execute_db_command(post_update_query, (post_id, ),
                                              commit=True)

            # Add a record in the like table
            like_insert_query = (
                "INSERT INTO 'like' (post_id, user_id, created_at) "
                "VALUES (?, ?, ?)")
            self.pl_utils._execute_db_command(like_insert_query,
                                              (post_id, user_id, current_time),
                                              commit=True)
            # Get the ID of the newly inserted like record
            like_id = self.db_cursor.lastrowid

            # Record the action in the trace table
            # if post has been reposted, record the root post id into trace
            action_info = {"post_id": post_id, "like_id": like_id}
            self.pl_utils._record_trace(user_id, ActionType.LIKE_POST.value,
                                        action_info, current_time)
            return {"success": True, "like_id": like_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def unlike_post(self, agent_id: int, post_id: int):
        try:
            post_type_result = self.pl_utils._get_post_type(post_id)
            if post_type_result['type'] == 'repost':
                post_id = post_type_result['root_post_id']
            user_id = agent_id

            # Check if a like record already exists
            like_check_query = ("SELECT * FROM 'like' WHERE post_id = ? AND "
                                "user_id = ?")
            self.pl_utils._execute_db_command(like_check_query,
                                              (post_id, user_id))
            result = self.db_cursor.fetchone()

            if not result:
                # No like record exists
                return {
                    "success": False,
                    "error": "Like record does not exist."
                }

            # Get the `like_id`
            like_id, _, _, _ = result

            # Update the number of likes in the post table
            post_update_query = (
                "UPDATE post SET num_likes = num_likes - 1 WHERE post_id = ?")
            self.pl_utils._execute_db_command(
                post_update_query,
                (post_id, ),
                commit=True,
            )

            # Delete the record in the like table
            like_delete_query = "DELETE FROM 'like' WHERE like_id = ?"
            self.pl_utils._execute_db_command(
                like_delete_query,
                (like_id, ),
                commit=True,
            )

            # Record the action in the trace table
            action_info = {"post_id": post_id, "like_id": like_id}
            self.pl_utils._record_trace(user_id, ActionType.UNLIKE_POST.value,
                                        action_info)
            return {"success": True, "like_id": like_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def dislike_post(self, agent_id: int, post_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            post_type_result = self.pl_utils._get_post_type(post_id)
            if post_type_result['type'] == 'repost':
                post_id = post_type_result['root_post_id']
            user_id = agent_id
            # Check if a dislike record already exists
            like_check_query = (
                "SELECT * FROM 'dislike' WHERE post_id = ? AND user_id = ?")
            self.pl_utils._execute_db_command(like_check_query,
                                              (post_id, user_id))
            if self.db_cursor.fetchone():
                # Dislike record already exists
                return {
                    "success": False,
                    "error": "Dislike record already exists."
                }

            # Check if the post to be disliked is self-posted
            if self.allow_self_rating is False:
                check_result = self.pl_utils._check_self_post_rating(
                    post_id, user_id)
                if check_result:
                    return check_result

            # Update the number of dislikes in the post table
            post_update_query = (
                "UPDATE post SET num_dislikes = num_dislikes + 1 WHERE "
                "post_id = ?")
            self.pl_utils._execute_db_command(post_update_query, (post_id, ),
                                              commit=True)

            # Add a record in the dislike table
            dislike_insert_query = (
                "INSERT INTO 'dislike' (post_id, user_id, created_at) "
                "VALUES (?, ?, ?)")
            self.pl_utils._execute_db_command(dislike_insert_query,
                                              (post_id, user_id, current_time),
                                              commit=True)
            # Get the ID of the newly inserted dislike record
            dislike_id = self.db_cursor.lastrowid

            # Record the action in the trace table
            action_info = {"post_id": post_id, "dislike_id": dislike_id}
            self.pl_utils._record_trace(user_id, ActionType.DISLIKE_POST.value,
                                        action_info, current_time)
            return {"success": True, "dislike_id": dislike_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def undo_dislike_post(self, agent_id: int, post_id: int):
        try:
            post_type_result = self.pl_utils._get_post_type(post_id)
            if post_type_result['type'] == 'repost':
                post_id = post_type_result['root_post_id']
            user_id = agent_id

            # Check if a dislike record already exists
            like_check_query = (
                "SELECT * FROM 'dislike' WHERE post_id = ? AND user_id = ?")
            self.pl_utils._execute_db_command(like_check_query,
                                              (post_id, user_id))
            result = self.db_cursor.fetchone()

            if not result:
                # No dislike record exists
                return {
                    "success": False,
                    "error": "Dislike record does not exist."
                }

            # Get the `dislike_id`
            dislike_id, _, _, _ = result

            # Update the number of dislikes in the post table
            post_update_query = (
                "UPDATE post SET num_dislikes = num_dislikes - 1 WHERE "
                "post_id = ?")
            self.pl_utils._execute_db_command(
                post_update_query,
                (post_id, ),
                commit=True,
            )

            # Delete the record in the dislike table
            like_delete_query = "DELETE FROM 'dislike' WHERE dislike_id = ?"
            self.pl_utils._execute_db_command(
                like_delete_query,
                (dislike_id, ),
                commit=True,
            )

            # Record the action in the trace table
            action_info = {"post_id": post_id, "dislike_id": dislike_id}
            self.pl_utils._record_trace(user_id,
                                        ActionType.UNDO_DISLIKE_POST.value,
                                        action_info)
            return {"success": True, "dislike_id": dislike_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def search_posts(self, agent_id: int, query: str):
        try:
            user_id = agent_id
            # Update the SQL query to search by content, post_id, and user_id
            # simultaneously
            sql_query = (
                "SELECT post_id, user_id, original_post_id, content, "
                "quote_content, created_at, num_likes, num_dislikes, "
                "num_shares FROM post WHERE content LIKE ? OR CAST(post_id AS "
                "TEXT) LIKE ? OR CAST(user_id AS TEXT) LIKE ?")
            # Note: CAST is necessary because post_id and user_id are integers,
            # while the search query is a string type
            self.pl_utils._execute_db_command(
                sql_query,
                ("%" + query + "%", "%" + query + "%", "%" + query + "%"),
                commit=True,
            )
            results = self.db_cursor.fetchall()

            # Record the operation in the trace table
            action_info = {"query": query}
            self.pl_utils._record_trace(user_id, ActionType.SEARCH_POSTS.value,
                                        action_info)

            # If no results are found, return a dictionary indicating failure
            if not results:
                return {
                    "success": False,
                    "message": "No posts found matching the query.",
                }
            results_with_comments = self.pl_utils._add_comments_to_posts(
                results)

            return {"success": True, "posts": results_with_comments}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def search_user(self, agent_id: int, query: str):
        try:
            user_id = agent_id
            sql_query = (
                "SELECT user_id, user_name, name, bio, created_at, "
                "num_followings, num_followers "
                "FROM user "
                "WHERE user_name LIKE ? OR name LIKE ? OR bio LIKE ? OR "
                "CAST(user_id AS TEXT) LIKE ?")
            # Rewrite to use the execute_db_command method
            self.pl_utils._execute_db_command(
                sql_query,
                (
                    "%" + query + "%",
                    "%" + query + "%",
                    "%" + query + "%",
                    "%" + query + "%",
                ),
                commit=True,
            )
            results = self.db_cursor.fetchall()

            # Record the operation in the trace table
            action_info = {"query": query}
            self.pl_utils._record_trace(user_id, ActionType.SEARCH_USER.value,
                                        action_info)

            # If no results are found, return a dict indicating failure
            if not results:
                return {
                    "success": False,
                    "message": "No users found matching the query.",
                }

            # Convert each tuple in results into a dictionary
            users = [{
                "user_id": user_id,
                "user_name": user_name,
                "name": name,
                "bio": bio,
                "created_at": created_at,
                "num_followings": num_followings,
                "num_followers": num_followers,
            } for user_id, user_name, name, bio, created_at, num_followings,
                     num_followers in results]
            return {"success": True, "users": users}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def follow(self, agent_id: int, followee_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id
            # Check if a follow record already exists
            follow_check_query = ("SELECT * FROM follow WHERE follower_id = ? "
                                  "AND followee_id = ?")
            self.pl_utils._execute_db_command(follow_check_query,
                                              (user_id, followee_id))
            if self.db_cursor.fetchone():
                # Follow record already exists
                return {
                    "success": False,
                    "error": "Follow record already exists."
                }

            # Add a record in the follow table
            follow_insert_query = (
                "INSERT INTO follow (follower_id, followee_id, created_at) "
                "VALUES (?, ?, ?)")
            self.pl_utils._execute_db_command(
                follow_insert_query, (user_id, followee_id, current_time),
                commit=True)
            # Get the ID of the newly inserted follow record
            follow_id = self.db_cursor.lastrowid

            # Update the following field in the user table
            user_update_query1 = (
                "UPDATE user SET num_followings = num_followings + 1 "
                "WHERE user_id = ?")
            self.pl_utils._execute_db_command(user_update_query1, (user_id, ),
                                              commit=True)

            # Update the follower field in the user table
            user_update_query2 = (
                "UPDATE user SET num_followers = num_followers + 1 "
                "WHERE user_id = ?")
            self.pl_utils._execute_db_command(user_update_query2,
                                              (followee_id, ),
                                              commit=True)

            # Record the operation in the trace table
            action_info = {"follow_id": follow_id}
            self.pl_utils._record_trace(user_id, ActionType.FOLLOW.value,
                                        action_info, current_time)
            # twitter_log.info(f"Trace inserted: user_id={user_id}, "
            #                  f"current_time={current_time}, "
            #                  f"action={ActionType.FOLLOW.value}, "
            #                  f"info={action_info}")
            return {"success": True, "follow_id": follow_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def unfollow(self, agent_id: int, followee_id: int):
        try:
            user_id = agent_id
            # Check for the existence of a follow record and get its ID
            follow_check_query = (
                "SELECT follow_id FROM follow WHERE follower_id = ? AND "
                "followee_id = ?")
            self.pl_utils._execute_db_command(follow_check_query,
                                              (user_id, followee_id))
            follow_record = self.db_cursor.fetchone()
            if not follow_record:
                return {
                    "success": False,
                    "error": "Follow record does not exist."
                }
            # Assuming ID is in the first column of the result
            follow_id = follow_record[0]

            # Delete the record in the follow table
            follow_delete_query = "DELETE FROM follow WHERE follow_id = ?"
            self.pl_utils._execute_db_command(follow_delete_query,
                                              (follow_id, ),
                                              commit=True)

            # Update the following field in the user table
            user_update_query1 = (
                "UPDATE user SET num_followings = num_followings - 1 "
                "WHERE user_id = ?")
            self.pl_utils._execute_db_command(user_update_query1, (user_id, ),
                                              commit=True)

            # Update the follower field in the user table
            user_update_query2 = (
                "UPDATE user SET num_followers = num_followers - 1 "
                "WHERE user_id = ?")
            self.pl_utils._execute_db_command(user_update_query2,
                                              (followee_id, ),
                                              commit=True)

            # Record the operation in the trace table
            action_info = {"followee_id": followee_id}
            self.pl_utils._record_trace(user_id, ActionType.UNFOLLOW.value,
                                        action_info)
            return {
                "success": True,
                "follow_id": follow_id,
            }  # Return the ID of the deleted follow record
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def mute(self, agent_id: int, mutee_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id
            # Check if a mute record already exists
            mute_check_query = ("SELECT * FROM mute WHERE muter_id = ? AND "
                                "mutee_id = ?")
            self.pl_utils._execute_db_command(mute_check_query,
                                              (user_id, mutee_id))
            if self.db_cursor.fetchone():
                # Mute record already exists
                return {
                    "success": False,
                    "error": "Mute record already exists."
                }
            # Add a record in the mute table
            mute_insert_query = (
                "INSERT INTO mute (muter_id, mutee_id, created_at) "
                "VALUES (?, ?, ?)")
            self.pl_utils._execute_db_command(
                mute_insert_query, (user_id, mutee_id, current_time),
                commit=True)
            # Get the ID of the newly inserted mute record
            mute_id = self.db_cursor.lastrowid

            # Record the operation in the trace table
            action_info = {"mutee_id": mutee_id}
            self.pl_utils._record_trace(user_id, ActionType.MUTE.value,
                                        action_info, current_time)
            return {"success": True, "mute_id": mute_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def unmute(self, agent_id: int, mutee_id: int):
        try:
            user_id = agent_id
            # Check for the specified mute record and get mute_id
            mute_check_query = (
                "SELECT mute_id FROM mute WHERE muter_id = ? AND mutee_id = ?")
            self.pl_utils._execute_db_command(mute_check_query,
                                              (user_id, mutee_id))
            mute_record = self.db_cursor.fetchone()
            if not mute_record:
                # If no mute record exists
                return {"success": False, "error": "No mute record exists."}
            mute_id = mute_record[0]

            # Delete the specified mute record from the mute table
            mute_delete_query = "DELETE FROM mute WHERE mute_id = ?"
            self.pl_utils._execute_db_command(mute_delete_query, (mute_id, ),
                                              commit=True)

            # Record the unmute operation in the trace table
            action_info = {"mutee_id": mutee_id}
            self.pl_utils._record_trace(user_id, ActionType.UNMUTE.value,
                                        action_info)
            return {"success": True, "mute_id": mute_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def trend(self, agent_id: int):
        """
        Get the top K trending posts in the last num_days days.
        """
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id
            # Calculate the start time for the search
            if self.recsys_type == RecsysType.REDDIT:
                start_time = current_time - timedelta(days=self.trend_num_days)
            else:
                start_time = int(current_time) - self.trend_num_days * 24 * 60

            # Build the SQL query
            sql_query = """
                SELECT post_id, user_id, original_post_id, content,
                quote_content, created_at, num_likes, num_dislikes,
                num_shares FROM post
                WHERE created_at >= ?
                ORDER BY num_likes DESC
                LIMIT ?
            """
            # Execute the database query
            self.pl_utils._execute_db_command(sql_query,
                                              (start_time, self.trend_top_k),
                                              commit=True)
            results = self.db_cursor.fetchall()

            # If no results were found, return a dictionary indicating failure
            if not results:
                return {
                    "success": False,
                    "message": "No trending posts in the specified period.",
                }
            results_with_comments = self.pl_utils._add_comments_to_posts(
                results)

            action_info = {"posts": results_with_comments}
            self.pl_utils._record_trace(user_id, ActionType.TREND.value,
                                        action_info, current_time)

            return {"success": True, "posts": results_with_comments}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def create_comment(self, agent_id: int, comment_message: tuple):
        post_id, content = comment_message
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            post_type_result = self.pl_utils._get_post_type(post_id)
            if post_type_result['type'] == 'repost':
                post_id = post_type_result['root_post_id']
            user_id = agent_id

            # Insert the comment record
            comment_insert_query = (
                "INSERT INTO comment (post_id, user_id, content, created_at) "
                "VALUES (?, ?, ?, ?)")
            self.pl_utils._execute_db_command(
                comment_insert_query,
                (post_id, user_id, content, current_time),
                commit=True,
            )
            comment_id = self.db_cursor.lastrowid

            # Prepare information for the trace record
            action_info = {"content": content, "comment_id": comment_id}
            self.pl_utils._record_trace(user_id,
                                        ActionType.CREATE_COMMENT.value,
                                        action_info, current_time)

            return {"success": True, "comment_id": comment_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def like_comment(self, agent_id: int, comment_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            # Check if a like record already exists
            like_check_query = (
                "SELECT * FROM comment_like WHERE comment_id = ? AND "
                "user_id = ?")
            self.pl_utils._execute_db_command(like_check_query,
                                              (comment_id, user_id))
            if self.db_cursor.fetchone():
                # Like record already exists
                return {
                    "success": False,
                    "error": "Comment like record already exists.",
                }

            # Check if the comment to be liked was posted by oneself
            if self.allow_self_rating is False:
                check_result = self.pl_utils._check_self_comment_rating(
                    comment_id, user_id)
                if check_result:
                    return check_result

            # Update the number of likes in the comment table
            comment_update_query = (
                "UPDATE comment SET num_likes = num_likes + 1 WHERE "
                "comment_id = ?")
            self.pl_utils._execute_db_command(comment_update_query,
                                              (comment_id, ),
                                              commit=True)

            # Add a record in the comment_like table
            like_insert_query = (
                "INSERT INTO comment_like (comment_id, user_id, created_at) "
                "VALUES (?, ?, ?)")
            self.pl_utils._execute_db_command(
                like_insert_query, (comment_id, user_id, current_time),
                commit=True)
            # Get the ID of the newly inserted like record
            comment_like_id = self.db_cursor.lastrowid

            # Record the operation in the trace table
            action_info = {
                "comment_id": comment_id,
                "comment_like_id": comment_like_id
            }
            self.pl_utils._record_trace(user_id, ActionType.LIKE_COMMENT.value,
                                        action_info, current_time)
            return {"success": True, "comment_like_id": comment_like_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def unlike_comment(self, agent_id: int, comment_id: int):
        try:
            user_id = agent_id

            # Check if a like record already exists
            like_check_query = (
                "SELECT * FROM comment_like WHERE comment_id = ? AND "
                "user_id = ?")
            self.pl_utils._execute_db_command(like_check_query,
                                              (comment_id, user_id))
            result = self.db_cursor.fetchone()

            if not result:
                # No like record exists
                return {
                    "success": False,
                    "error": "Comment like record does not exist.",
                }
            # Get the `comment_like_id`
            comment_like_id = result[0]

            # Update the number of likes in the comment table
            comment_update_query = (
                "UPDATE comment SET num_likes = num_likes - 1 WHERE "
                "comment_id = ?")
            self.pl_utils._execute_db_command(
                comment_update_query,
                (comment_id, ),
                commit=True,
            )
            # Delete the record in the comment_like table
            like_delete_query = ("DELETE FROM comment_like WHERE "
                                 "comment_like_id = ?")
            self.pl_utils._execute_db_command(
                like_delete_query,
                (comment_like_id, ),
                commit=True,
            )
            # Record the operation in the trace table
            action_info = {
                "comment_id": comment_id,
                "comment_like_id": comment_like_id
            }
            self.pl_utils._record_trace(user_id,
                                        ActionType.UNLIKE_COMMENT.value,
                                        action_info)
            return {"success": True, "comment_like_id": comment_like_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def dislike_comment(self, agent_id: int, comment_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            # Check if a dislike record already exists
            dislike_check_query = (
                "SELECT * FROM comment_dislike WHERE comment_id = ? AND "
                "user_id = ?")
            self.pl_utils._execute_db_command(dislike_check_query,
                                              (comment_id, user_id))
            if self.db_cursor.fetchone():
                # Dislike record already exists
                return {
                    "success": False,
                    "error": "Comment dislike record already exists.",
                }

            # Check if the comment to be disliked was posted by oneself
            if self.allow_self_rating is False:
                check_result = self.pl_utils._check_self_comment_rating(
                    comment_id, user_id)
                if check_result:
                    return check_result

            # Update the number of dislikes in the comment table
            comment_update_query = (
                "UPDATE comment SET num_dislikes = num_dislikes + 1 WHERE "
                "comment_id = ?")
            self.pl_utils._execute_db_command(comment_update_query,
                                              (comment_id, ),
                                              commit=True)

            # Add a record in the comment_dislike table
            dislike_insert_query = (
                "INSERT INTO comment_dislike (comment_id, user_id, "
                "created_at) VALUES (?, ?, ?)")
            self.pl_utils._execute_db_command(
                dislike_insert_query, (comment_id, user_id, current_time),
                commit=True)
            # Get the ID of the newly inserted dislike record
            comment_dislike_id = (self.db_cursor.lastrowid)

            # Record the operation in the trace table
            action_info = {
                "comment_id": comment_id,
                "comment_dislike_id": comment_dislike_id,
            }
            self.pl_utils._record_trace(user_id,
                                        ActionType.DISLIKE_COMMENT.value,
                                        action_info, current_time)
            return {"success": True, "comment_dislike_id": comment_dislike_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def undo_dislike_comment(self, agent_id: int, comment_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            # Check if a dislike record already exists
            dislike_check_query = (
                "SELECT comment_dislike_id FROM comment_dislike WHERE "
                "comment_id = ? AND user_id = ?")
            self.pl_utils._execute_db_command(dislike_check_query,
                                              (comment_id, user_id))
            dislike_record = self.db_cursor.fetchone()
            if not dislike_record:
                # No dislike record exists
                return {
                    "success": False,
                    "error": "Comment dislike record does not exist.",
                }
            comment_dislike_id = dislike_record[0]

            # Delete the record from the comment_dislike table
            dislike_delete_query = (
                "DELETE FROM comment_dislike WHERE comment_id = ? AND "
                "user_id = ?")
            self.pl_utils._execute_db_command(dislike_delete_query,
                                              (comment_id, user_id),
                                              commit=True)

            # Update the number of dislikes in the comment table
            comment_update_query = (
                "UPDATE comment SET num_dislikes = num_dislikes - 1 WHERE "
                "comment_id = ?")
            self.pl_utils._execute_db_command(comment_update_query,
                                              (comment_id, ),
                                              commit=True)

            # Record the operation in the trace table
            action_info = {
                "comment_id": comment_id,
                "comment_dislike_id": comment_dislike_id,
            }
            self.pl_utils._record_trace(user_id,
                                        ActionType.UNDO_DISLIKE_COMMENT.value,
                                        action_info, current_time)
            return {"success": True, "comment_dislike_id": comment_dislike_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def do_nothing(self, agent_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            action_info = {}
            self.pl_utils._record_trace(user_id, ActionType.DO_NOTHING.value,
                                        action_info, current_time)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def interview(self, agent_id: int, interview_data):
        """Interview an agent with the given prompt and record the response.

        Args:
            agent_id (int): The ID of the agent being interviewed.
            interview_data: Either a string (prompt only) or dict with prompt
                and response.

        Returns:
            dict: A dictionary with success status.
        """
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            # Handle both old format (string prompt) and new format
            # (dict with prompt + response)
            if isinstance(interview_data, str):
                # Old format: just the prompt
                prompt = interview_data
                response = None
                interview_id = f"{current_time}_{user_id}"
                action_info = {"prompt": prompt, "interview_id": interview_id}
            else:
                # New format: dict with prompt and response
                prompt = interview_data.get("prompt", "")
                response = interview_data.get("response", "")
                interview_id = f"{current_time}_{user_id}"
                action_info = {
                    "prompt": prompt,
                    "response": response,
                    "interview_id": interview_id
                }

            # Record the interview in the trace table
            self.pl_utils._record_trace(user_id, ActionType.INTERVIEW.value,
                                        action_info, current_time)

            return {"success": True, "interview_id": interview_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def report_post(self, agent_id: int, report_message: tuple):
        post_id, report_reason = report_message
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id
            post_type_result = self.pl_utils._get_post_type(post_id)

            # Check if a report record already exists
            check_report_query = (
                "SELECT * FROM report WHERE user_id = ? AND post_id = ?")
            self.pl_utils._execute_db_command(check_report_query,
                                              (user_id, post_id))
            if self.db_cursor.fetchone():
                return {
                    "success": False,
                    "error": "Report record already exists."
                }

            if not post_type_result:
                return {"success": False, "error": "Post not found."}

            # Update the number of reports in the post table
            update_reports_query = (
                "UPDATE post SET num_reports = num_reports + 1 WHERE "
                "post_id = ?")
            self.pl_utils._execute_db_command(update_reports_query,
                                              (post_id, ),
                                              commit=True)

            # Add a report in the report table
            report_insert_query = (
                "INSERT INTO report (post_id, user_id, report_reason, "
                "created_at) VALUES (?, ?, ?, ?)")
            self.pl_utils._execute_db_command(
                report_insert_query,
                (post_id, user_id, report_reason, current_time),
                commit=True)

            # Get the ID of the newly inserted report record
            report_id = self.db_cursor.lastrowid

            # Record the action in the trace table
            action_info = {"post_id": post_id, "report_id": report_id}
            self.pl_utils._record_trace(user_id, ActionType.REPORT_POST.value,
                                        action_info, current_time)

            return {"success": True, "report_id": report_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_to_group(self, agent_id: int, message: tuple):
        group_id, content = message
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id
            # check if user is a member of the group
            check_query = ("SELECT * FROM group_members WHERE group_id = ? "
                           "AND agent_id = ?")
            self.pl_utils._execute_db_command(check_query, (group_id, user_id))
            if not self.db_cursor.fetchone():
                return {
                    "success": False,
                    "error": "User is not a member of this group.",
                }

            # Insert the message into the group_messages table
            insert_query = """
                INSERT INTO group_messages
                (group_id, sender_id, content, sent_at)
                VALUES (?, ?, ?, ?)
            """
            self.pl_utils._execute_db_command(
                insert_query, (group_id, user_id, content, current_time),
                commit=True)
            message_id = self.db_cursor.lastrowid

            # get the group members
            members_query = ("SELECT agent_id FROM group_members WHERE "
                             "group_id = ? AND agent_id != ?")
            self.pl_utils._execute_db_command(members_query,
                                              (group_id, user_id))
            members = [row[0] for row in self.db_cursor.fetchall()]
            action_info = {
                "group_id": group_id,
                "message_id": message_id,
                "content": content,
            }
            self.pl_utils._record_trace(user_id,
                                        ActionType.SEND_TO_GROUP.value,
                                        action_info, current_time)

            return {"success": True, "message_id": message_id, "to": members}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def create_group(self, agent_id: int, group_name: str):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            # insert the group into the groups table
            insert_query = """
                INSERT INTO chat_group (name, created_at) VALUES (?, ?)
            """
            self.pl_utils._execute_db_command(insert_query,
                                              (group_name, current_time),
                                              commit=True)
            group_id = self.db_cursor.lastrowid

            # insert the user as a member of the group
            join_query = """
                INSERT INTO group_members (group_id, agent_id, joined_at)
                VALUES (?, ?, ?)
            """
            self.pl_utils._execute_db_command(
                join_query, (group_id, user_id, current_time), commit=True)

            action_info = {"group_id": group_id, "group_name": group_name}
            self.pl_utils._record_trace(user_id, ActionType.CREATE_GROUP.value,
                                        action_info, current_time)

            return {"success": True, "group_id": group_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def join_group(self, agent_id: int, group_id: int):
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()
        try:
            user_id = agent_id

            # check if group exists
            check_group_query = """SELECT * FROM chat_group
                WHERE group_id = ?"""
            self.pl_utils._execute_db_command(check_group_query, (group_id, ))
            if not self.db_cursor.fetchone():
                return {"success": False, "error": "Group does not exist."}

            # check if user is already in the group
            check_member_query = (
                "SELECT * FROM group_members WHERE group_id = ? "
                "AND agent_id = ?")
            self.pl_utils._execute_db_command(check_member_query,
                                              (group_id, user_id))
            if self.db_cursor.fetchone():
                return {
                    "success": False,
                    "error": "User is already in the group."
                }

            # join the group
            join_query = """
                INSERT INTO group_members
                (group_id, agent_id, joined_at) VALUES (?, ?, ?)
            """
            self.pl_utils._execute_db_command(
                join_query, (group_id, user_id, current_time), commit=True)

            action_info = {"group_id": group_id}
            self.pl_utils._record_trace(user_id, ActionType.JOIN_GROUP.value,
                                        action_info, current_time)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def leave_group(self, agent_id: int, group_id: int):
        try:
            user_id = agent_id

            # check if user is a member of the group
            check_query = ("SELECT * FROM group_members "
                           "WHERE group_id = ? AND agent_id = ?")
            self.pl_utils._execute_db_command(check_query, (group_id, user_id))
            if not self.db_cursor.fetchone():
                return {
                    "success": False,
                    "error": "User is not a member of this group."
                }

            # delete the member record
            delete_query = ("DELETE FROM group_members "
                            "WHERE group_id = ? AND agent_id = ?")
            self.pl_utils._execute_db_command(delete_query,
                                              (group_id, user_id),
                                              commit=True)

            action_info = {"group_id": group_id}
            self.pl_utils._record_trace(user_id, ActionType.LEAVE_GROUP.value,
                                        action_info)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def listen_from_group(self, agent_id: int):
        try:
            # get all groups Dict[group_id, group_name]
            query = """ SELECT * FROM chat_group """
            self.pl_utils._execute_db_command(query)
            all_groups = {}
            for row in self.db_cursor.fetchall():
                all_groups[row[0]] = row[1]

            # get all groups that the user is a member of
            in_query = """
                SELECT group_id FROM group_members WHERE agent_id = ?
            """
            self.pl_utils._execute_db_command(in_query, (agent_id, ))
            joined_group_ids = [row[0] for row in self.db_cursor.fetchall()]

            # get all messages from those groups, Dict[group_id, [messages]]
            messages = {}
            for group_id in joined_group_ids:
                select_query = """
                    SELECT message_id, content, sender_id,
                    sent_at FROM group_messages WHERE group_id = ?
                """
                self.pl_utils._execute_db_command(select_query, (group_id, ))
                messages[group_id] = [{
                    "message_id": row[0],
                    "content": row[1],
                    "sender_id": row[2],
                    "sent_at": row[3],
                } for row in self.db_cursor.fetchall()]

            return {
                "success": True,
                "all_groups": all_groups,
                "joined_groups": joined_group_ids,
                "messages": messages
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
