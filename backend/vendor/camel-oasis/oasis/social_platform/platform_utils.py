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
import json
from datetime import datetime

from oasis.social_platform.typing import RecsysType


class PlatformUtils:

    def __init__(self,
                 db,
                 db_cursor,
                 start_time,
                 sandbox_clock,
                 show_score,
                 recsys_type,
                 report_threshold=1):
        self.db = db
        self.db_cursor = db_cursor
        self.start_time = start_time
        self.sandbox_clock = sandbox_clock
        self.show_score = show_score
        self.recsys_type = recsys_type
        self.report_threshold = report_threshold

    @staticmethod
    def _not_signup_error_message(agent_id):
        return {
            "success":
            False,
            "error": (f"Agent {agent_id} has not signed up and does not have "
                      f"a user id."),
        }

    def _execute_db_command(self, command, args=(), commit=False):
        self.db_cursor.execute(command, args)
        if commit:
            self.db.commit()
        return self.db_cursor

    def _execute_many_db_command(self, command, args_list, commit=False):
        self.db_cursor.executemany(command, args_list)
        if commit:
            self.db.commit()
        return self.db_cursor

    def _check_agent_userid(self, agent_id):
        try:
            user_query = "SELECT user_id FROM user WHERE agent_id = ?"
            results = self._execute_db_command(user_query, (agent_id, ))
            # Fetch the first row of the query result
            first_row = results.fetchone()
            if first_row:
                user_id = first_row[0]
                return user_id
            else:
                return None
        except Exception as e:
            # Log or handle the error as appropriate
            print(f"Error querying user_id for agent_id {agent_id}: {e}")
            return None

    def _add_comments_to_posts(self, posts_results):
        # Initialize the returned posts list
        posts = []
        for row in posts_results:
            (post_id, user_id, original_post_id, content, quote_content,
             created_at, num_likes, num_dislikes, num_shares) = row
            post_type_result = self._get_post_type(post_id)
            if post_type_result is None:
                continue
            original_user_id_query = (
                "SELECT user_id FROM post WHERE post_id = ?")
            if post_type_result["type"] == "repost":
                self.db_cursor.execute(original_user_id_query,
                                       (original_post_id, ))
                original_user_id = self.db_cursor.fetchone()[0]
                original_post_id = post_id
                post_id = post_type_result["root_post_id"]
                self.db_cursor.execute(
                    "SELECT content, quote_content, created_at, num_likes, "
                    "num_dislikes, num_shares, num_reports FROM post "
                    "WHERE post_id = ?", (post_id, ))
                original_post_result = self.db_cursor.fetchone()
                (content, quote_content, created_at, num_likes, num_dislikes,
                 num_shares, num_reports) = original_post_result
                post_content = (
                    f"User {user_id} reposted a post from User "
                    f"{original_user_id}. Repost content: {content}. ")

            elif post_type_result["type"] == "quote":
                self.db_cursor.execute(original_user_id_query,
                                       (original_post_id, ))
                original_user_id = self.db_cursor.fetchone()[0]
                post_content = (
                    f"User {user_id} quoted a post from User "
                    f"{original_user_id}. Quote content: {quote_content}. "
                    f"Original Content: {content}")

            elif post_type_result["type"] == "common":
                post_content = content
                # Get num_reports for common posts
                self.db_cursor.execute(
                    "SELECT num_reports FROM post WHERE post_id = ?",
                    (post_id, ))
                num_reports = self.db_cursor.fetchone()[0]

            # For each post, query its corresponding comments
            self.db_cursor.execute(
                "SELECT comment_id, post_id, user_id, content, created_at, "
                "num_likes, num_dislikes FROM comment WHERE post_id = ?",
                (post_id, ),
            )
            comments_results = self.db_cursor.fetchall()

            # Convert each comment's result into dictionary format
            comments = [{
                "comment_id":
                comment_id,
                "post_id":
                post_id,
                "user_id":
                user_id,
                "content":
                content,
                "created_at":
                created_at,
                **({
                    "score": num_likes - num_dislikes
                } if self.show_score else {
                       "num_likes": num_likes,
                       "num_dislikes": num_dislikes
                   }),
            } for (
                comment_id,
                post_id,
                user_id,
                content,
                created_at,
                num_likes,
                num_dislikes,
            ) in comments_results]

            # Add warning message if the post has been reported
            if num_reports >= self.report_threshold:
                warning_message = ("[Warning: This post has been reported"
                                   f" {num_reports} times]")
                post_content = f"{warning_message}\n{post_content}"

            # Add post information and corresponding comments to the posts list
            posts.append({
                "post_id":
                post_id
                if post_type_result["type"] != "repost" else original_post_id,
                "user_id":
                user_id,
                "content":
                post_content,
                "created_at":
                created_at,
                **({
                    "score": num_likes - num_dislikes
                } if self.show_score else {
                       "num_likes": num_likes,
                       "num_dislikes": num_dislikes
                   }),
                "num_shares":
                num_shares,
                "num_reports":
                num_reports,
                "comments":
                comments,
            })
        return posts

    def _record_trace(self,
                      user_id,
                      action_type,
                      action_info,
                      current_time=None):
        r"""If, in addition to the trace, the operation function also records
        time in other tables of the database, use the time of entering
        the operation function for consistency.

        Pass in current_time to make, for example, the created_at in the post
        table exactly the same as the time in the trace table.

        If only the trace table needs to record time, use the entry time into
        _record_trace as the time for the trace record.
        """
        if self.recsys_type == RecsysType.REDDIT:
            current_time = self.sandbox_clock.time_transfer(
                datetime.now(), self.start_time)
        else:
            current_time = self.sandbox_clock.get_time_step()

        trace_insert_query = (
            "INSERT INTO trace (user_id, created_at, action, info) "
            "VALUES (?, ?, ?, ?)")
        action_info_str = json.dumps(action_info)
        self._execute_db_command(
            trace_insert_query,
            (user_id, current_time, action_type, action_info_str),
            commit=True,
        )

    def _check_self_post_rating(self, post_id, user_id):
        self_like_check_query = "SELECT user_id FROM post WHERE post_id = ?"
        self._execute_db_command(self_like_check_query, (post_id, ))
        result = self.db_cursor.fetchone()
        if result and result[0] == user_id:
            error_message = ("Users are not allowed to like/dislike their own "
                             "posts.")
            return {"success": False, "error": error_message}
        else:
            return None

    def _check_self_comment_rating(self, comment_id, user_id):
        self_like_check_query = ("SELECT user_id FROM comment WHERE "
                                 "comment_id = ?")
        self._execute_db_command(self_like_check_query, (comment_id, ))
        result = self.db_cursor.fetchone()
        if result and result[0] == user_id:
            error_message = ("Users are not allowed to like/dislike their "
                             "own comments.")
            return {"success": False, "error": error_message}
        else:
            return None

    def _get_post_type(self, post_id: int):
        query = (
            "SELECT original_post_id, quote_content FROM post WHERE post_id "
            "= ?")
        self._execute_db_command(query, (post_id, ))
        result = self.db_cursor.fetchone()

        if not result:
            return None

        original_post_id, quote_content = result

        if original_post_id is None:
            # common post without quote or repost
            return {"type": "common", "root_post_id": None}
        elif quote_content is None:
            # post with repost
            return {"type": "repost", "root_post_id": original_post_id}
        else:
            # post with quote
            return {"type": "quote", "root_post_id": original_post_id}
