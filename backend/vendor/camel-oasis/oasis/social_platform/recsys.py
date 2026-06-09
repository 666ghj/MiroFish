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
'''Note that you need to check if it exceeds max_rec_post_len when writing
into rec_matrix'''
import heapq
import logging
import random
import time
from ast import literal_eval
from datetime import datetime
from math import log
from typing import Any, Dict, List

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .process_recsys_posts import (generate_post_vector,
                                   generate_post_vector_openai)
from .typing import ActionType, RecsysType

rec_log = logging.getLogger(name='social.rec')
rec_log.setLevel('DEBUG')

# Initially set to None, to be assigned once again in the recsys function
model = None
twhin_tokenizer = None
twhin_model = None

# Create the TF-IDF model
tfidf_vectorizer = TfidfVectorizer()
# Prepare the twhin model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# All historical tweets and the most recent tweet of each user
user_previous_post_all = {}
user_previous_post = {}
user_profiles = []
# Get the {post_id: content} dict
t_items = {}
# Get the {uid: follower_count} dict
# It's necessary to ensure that agent registration is sequential, with the
# relationship of user_id=agent_id+1; disorder in registration will cause
# issues here
u_items = {}
# Get the creation times of all tweets, assigning scores based on how recent
# they are
date_score = []


def get_twhin_tokenizer():
    global twhin_tokenizer
    if twhin_tokenizer is None:
        from transformers import AutoTokenizer
        twhin_tokenizer = AutoTokenizer.from_pretrained(
            pretrained_model_name_or_path="Twitter/twhin-bert-base",
            model_max_length=512)
    return twhin_tokenizer


def get_twhin_model(device):
    global twhin_model
    if twhin_model is None:
        from transformers import AutoModel
        twhin_model = AutoModel.from_pretrained(
            pretrained_model_name_or_path="Twitter/twhin-bert-base").to(device)
    return twhin_model


def load_model(model_name):
    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if model_name == 'paraphrase-MiniLM-L6-v2':
            return SentenceTransformer(model_name,
                                       device=device,
                                       cache_folder="./models")
        elif model_name == 'Twitter/twhin-bert-base':
            twhin_tokenizer = get_twhin_tokenizer()
            twhin_model = get_twhin_model(device)
            return twhin_tokenizer, twhin_model
        else:
            raise ValueError(f"Unknown model name: {model_name}")
    except Exception as e:
        raise Exception(f"Failed to load the model: {model_name}") from e


def get_recsys_model(recsys_type: str = None):
    if recsys_type == RecsysType.TWITTER.value:
        model = load_model('paraphrase-MiniLM-L6-v2')
        return model
    elif recsys_type == RecsysType.TWHIN.value:
        twhin_tokenizer, twhin_model = load_model("Twitter/twhin-bert-base")
        models = (twhin_tokenizer, twhin_model)
        return models
    elif (recsys_type == RecsysType.REDDIT.value
          or recsys_type == RecsysType.RANDOM.value):
        return None
    else:
        raise ValueError(f"Unknown recsys type: {recsys_type}")


# Move model to GPU if available
device = 'cuda' if torch.cuda.is_available() else 'cpu'
if model is not None:
    model.to(device)
else:
    pass


# Reset global variables
def reset_globals():
    global user_previous_post_all, user_previous_post
    global user_profiles, t_items, u_items
    global date_score
    user_previous_post_all = {}
    user_previous_post = {}
    user_profiles = []
    t_items = {}
    u_items = {}
    date_score = []


def rec_sys_random(post_table: List[Dict[str, Any]], rec_matrix: List[List],
                   max_rec_post_len: int) -> List[List]:
    """
    Randomly recommend posts to users.

    Args:
        user_table (List[Dict[str, Any]]): List of users.
        post_table (List[Dict[str, Any]]): List of posts.
        trace_table (List[Dict[str, Any]]): List of user interactions.
        rec_matrix (List[List]): Existing recommendation matrix.
        max_rec_post_len (int): Maximum number of recommended posts.

    Returns:
        List[List]: Updated recommendation matrix.
    """
    # Get all post IDs
    post_ids = [post['post_id'] for post in post_table]
    new_rec_matrix = []
    if len(post_ids) <= max_rec_post_len:
        # If the number of posts is less than or equal to the maximum number
        # of recommendations, each user gets all post IDs
        new_rec_matrix = [post_ids] * len(rec_matrix)
    else:
        # If the number of posts is greater than the maximum number of
        # recommendations, each user randomly gets a specified number of post
        # IDs
        for _ in range(len(rec_matrix)):
            new_rec_matrix.append(random.sample(post_ids, max_rec_post_len))

    return new_rec_matrix


def calculate_hot_score(num_likes: int, num_dislikes: int,
                        created_at: datetime) -> int:
    """
    Compute the hot score for a post.

    Args:
        num_likes (int): Number of likes.
        num_dislikes (int): Number of dislikes.
        created_at (datetime): Creation time of the post.

    Returns:
        int: Hot score of the post.

    Reference:
        https://medium.com/hacking-and-gonzo/how-reddit-ranking-algorithms-work-ef111e33d0d9
    """
    s = num_likes - num_dislikes
    order = log(max(abs(s), 1), 10)
    sign = 1 if s > 0 else -1 if s < 0 else 0

    # epoch_seconds
    epoch = datetime(1970, 1, 1)
    td = created_at - epoch
    epoch_seconds_result = td.days * 86400 + td.seconds + (
        float(td.microseconds) / 1e6)

    seconds = epoch_seconds_result - 1134028003
    return round(sign * order + seconds / 45000, 7)


def get_recommendations(
    user_index,
    cosine_similarities,
    items,
    score,
    top_n=100,
):
    similarities = np.array(cosine_similarities[user_index])
    similarities = similarities * score
    top_item_indices = similarities.argsort()[::-1][:top_n]
    recommended_items = [(list(items.keys())[i], similarities[i])
                         for i in top_item_indices]
    return recommended_items


def rec_sys_reddit(post_table: List[Dict[str, Any]], rec_matrix: List[List],
                   max_rec_post_len: int) -> List[List]:
    """
    Recommend posts based on Reddit-like hot score.

    Args:
        post_table (List[Dict[str, Any]]): List of posts.
        rec_matrix (List[List]): Existing recommendation matrix.
        max_rec_post_len (int): Maximum number of recommended posts.

    Returns:
        List[List]: Updated recommendation matrix.
    """
    # Get all post IDs
    post_ids = [post['post_id'] for post in post_table]

    if len(post_ids) <= max_rec_post_len:
        # If the number of posts is less than or equal to the maximum number
        # of recommendations, each user gets all post IDs
        new_rec_matrix = [post_ids] * len(rec_matrix)
    else:
        # The time complexity of this recommendation system is
        # O(post_num * log max_rec_post_len)
        all_hot_score = []
        for post in post_table:
            try:
                created_at_dt = datetime.strptime(post['created_at'],
                                                  "%Y-%m-%d %H:%M:%S.%f")
            except Exception:
                created_at_dt = datetime.strptime(post['created_at'],
                                                  "%Y-%m-%d %H:%M:%S")
            hot_score = calculate_hot_score(post['num_likes'],
                                            post['num_dislikes'],
                                            created_at_dt)
            all_hot_score.append((hot_score, post['post_id']))
        # Sort
        top_posts = heapq.nlargest(max_rec_post_len,
                                   all_hot_score,
                                   key=lambda x: x[0])
        top_post_ids = [post_id for _, post_id in top_posts]

        # If the number of posts is greater than the maximum number of
        # recommendations, each user gets a specified number of post IDs
        # randomly
        new_rec_matrix = [top_post_ids] * len(rec_matrix)

    return new_rec_matrix


def rec_sys_personalized(user_table: List[Dict[str, Any]],
                         post_table: List[Dict[str, Any]],
                         trace_table: List[Dict[str,
                                                Any]], rec_matrix: List[List],
                         max_rec_post_len: int) -> List[List]:
    """
    Recommend posts based on personalized similarity scores.

    Args:
        user_table (List[Dict[str, Any]]): List of users.
        post_table (List[Dict[str, Any]]): List of posts.
        trace_table (List[Dict[str, Any]]): List of user interactions.
        rec_matrix (List[List]): Existing recommendation matrix.
        max_rec_post_len (int): Maximum number of recommended posts.

    Returns:
        List[List]: Updated recommendation matrix.
    """
    global model
    if model is None or isinstance(model, tuple):
        model = get_recsys_model(recsys_type="twitter")

    post_ids = [post['post_id'] for post in post_table]
    print(
        f'Running personalized recommendation for {len(user_table)} users...')
    start_time = time.time()
    new_rec_matrix = []
    if len(post_ids) <= max_rec_post_len:
        # If the number of posts is less than or equal to the maximum
        # recommended length, each user gets all post IDs
        new_rec_matrix = [post_ids] * len(rec_matrix)
    else:
        # If the number of posts is greater than the maximum recommended
        # length, each user gets personalized post IDs
        user_bios = [
            user['bio'] if 'bio' in user and user['bio'] is not None else ''
            for user in user_table
        ]
        post_contents = [post['content'] for post in post_table]

        if model:
            user_embeddings = model.encode(user_bios,
                                           convert_to_tensor=True,
                                           device=device)
            post_embeddings = model.encode(post_contents,
                                           convert_to_tensor=True,
                                           device=device)

            # Compute dot product similarity
            dot_product = torch.matmul(user_embeddings, post_embeddings.T)

            # Compute norm
            user_norms = torch.norm(user_embeddings, dim=1)
            post_norms = torch.norm(post_embeddings, dim=1)

            # Compute cosine similarity
            similarities = dot_product / (user_norms[:, None] *
                                          post_norms[None, :])

        else:
            # Generate random similarities
            similarities = torch.rand(len(user_table), len(post_table))

        # Iterate through each user to generate personalized recommendations.
        for user_index, user in enumerate(user_table):
            # Filter out posts made by the current user.
            filtered_post_indices = [
                i for i, post in enumerate(post_table)
                if post['user_id'] != user['user_id']
            ]

            user_similarities = similarities[user_index, filtered_post_indices]

            # Get the corresponding post IDs for the filtered posts.
            filtered_post_ids = [
                post_table[i]['post_id'] for i in filtered_post_indices
            ]

            # Determine the top posts based on the similarities, limited by
            # max_rec_post_len.
            _, top_indices = torch.topk(user_similarities,
                                        k=min(max_rec_post_len,
                                              len(filtered_post_ids)))

            top_post_ids = [filtered_post_ids[i] for i in top_indices.tolist()]

            # Append the top post IDs to the new recommendation matrix.
            new_rec_matrix.append(top_post_ids)

    end_time = time.time()
    print(f'Personalized recommendation time: {end_time - start_time:.6f}s')
    return new_rec_matrix


def get_like_post_id(user_id, action, trace_table):
    """
    Get the post IDs that a user has liked or unliked.

    Args:
        user_id (str): ID of the user.
        action (str): Type of action (like or unlike).
        post_table (list): List of posts.
        trace_table (list): List of user interactions.

    Returns:
        list: List of post IDs.
    """
    # Get post IDs from trace table for the given user and action
    trace_post_ids = [
        literal_eval(trace['info'])["post_id"] for trace in trace_table
        if (trace['user_id'] == user_id and trace['action'] == action)
    ]
    """Only take the last 5 liked posts, if not enough, pad with the most
    recently liked post. Only take IDs, not content, because calculating
    embeddings for all posts again is very time-consuming, especially when the
    number of agents is large"""
    if len(trace_post_ids) < 5 and len(trace_post_ids) > 0:
        trace_post_ids += [trace_post_ids[-1]] * (5 - len(trace_post_ids))
    elif len(trace_post_ids) > 5:
        trace_post_ids = trace_post_ids[-5:]
    else:
        trace_post_ids = [0]

    return trace_post_ids


# Calculate the average cosine similarity between liked posts and target posts
def calculate_like_similarity(liked_vectors, target_vectors):
    # Calculate the norms of the vectors
    liked_norms = np.linalg.norm(liked_vectors, axis=1)
    target_norms = np.linalg.norm(target_vectors, axis=1)
    # Calculate dot products
    dot_products = np.dot(target_vectors, liked_vectors.T)
    # Calculate cosine similarities
    cosine_similarities = dot_products / np.outer(target_norms, liked_norms)
    # Take the average
    average_similarities = np.mean(cosine_similarities, axis=1)

    return average_similarities


def coarse_filtering(input_list, scale):
    """
    Coarse filtering posts and return selected elements with their indices.
    """
    if len(input_list) <= scale:
        # Return elements and their indices as list of tuples (element, index)
        sampled_indices = range(len(input_list))
        return (input_list, sampled_indices)
    else:
        # Get random sample of scale elements
        sampled_indices = random.sample(range(len(input_list)), scale)
        sampled_elements = [input_list[idx] for idx in sampled_indices]
        # return [(input_list[idx], idx) for idx in sampled_indices]
        return (sampled_elements, sampled_indices)


def rec_sys_personalized_twh(
        user_table: List[Dict[str, Any]],
        post_table: List[Dict[str, Any]],
        latest_post_count: int,
        trace_table: List[Dict[str, Any]],
        rec_matrix: List[List],
        max_rec_post_len: int,
        current_time: int,
        # source_post_indexs: List[int],
        recall_only: bool = False,
        enable_like_score: bool = False,
        use_openai_embedding: bool = False) -> List[List]:
    global twhin_model, twhin_tokenizer
    if twhin_model is None or twhin_tokenizer is None:
        twhin_tokenizer, twhin_model = get_recsys_model(
            recsys_type="twhin-bert")
    # Set some global variables to reduce time consumption
    global date_score, t_items, u_items, user_previous_post
    global user_previous_post_all, user_profiles
    # Get the uid: follower_count dict
    # Update only once, unless adding the feature to include new users midway.
    if (not u_items) or len(u_items) != len(user_table):
        u_items = {
            user['user_id']: user["num_followers"]
            for user in user_table
        }
    if not user_previous_post_all or len(user_previous_post_all) != len(
            user_table):
        # Each user must have a list of historical tweets
        user_previous_post_all = {
            index: []
            for index in range(len(user_table))
        }
        user_previous_post = {index: "" for index in range(len(user_table))}
    if not user_profiles or len(user_profiles) != len(user_table):
        for user in user_table:
            if user['bio'] is None:
                user_profiles.append('This user does not have profile')
            else:
                user_profiles.append(user['bio'])

    if len(t_items) < len(post_table):
        for post in post_table[-latest_post_count:]:
            # Get the {post_id: content} dict, update only the latest tweets
            t_items[post['post_id']] = post['content']
            # Update the user's historical tweets
            user_previous_post_all[post['user_id']].append(post['content'])
            user_previous_post[post['user_id']] = post['content']
            # Get the creation times of all tweets, assigning scores based on
            # how recent they are, note that this algorithm can run for a
            # maximum of 90 time steps
            date_score.append(
                np.log(
                    (271.8 - (current_time - int(post['created_at']))) / 100))

    date_score_np = np.array(date_score)

    if enable_like_score:
        # Calculate similarity with previously liked content, first gather
        # liked post ids from the trace
        like_post_ids_all = []
        for user in user_table:
            user_id = user['agent_id']
            like_post_ids = get_like_post_id(user_id,
                                             ActionType.LIKE_POST.value,
                                             trace_table)
            like_post_ids_all.append(like_post_ids)
    scores = date_score_np
    new_rec_matrix = []
    if len(post_table) <= max_rec_post_len:
        # If the number of tweets is less than or equal to the max
        # recommendation count, each user gets all post IDs
        tids = [t['post_id'] for t in post_table]
        new_rec_matrix = [tids] * (len(rec_matrix))

    else:
        # If the number of tweets is greater than the max recommendation
        # count, each user randomly gets personalized post IDs

        # This requires going through all users to update their profiles,
        # which is a time-consuming operation
        for post_user_index in user_previous_post:
            try:
                # Directly replacing the profile with the latest tweet will
                # cause the recommendation system to repeatedly push other
                # reposts to users who have already shared that tweet
                # user_profiles[post_user_index] =
                # user_previous_post[post_user_index]
                # Instead, append the description of the Recent post's content
                # to the end of the user char
                update_profile = (
                    f" # Recent post:{user_previous_post[post_user_index]}")
                if user_previous_post[post_user_index] != "":
                    # If there's no update for the recent post, add this part
                    if "# Recent post:" not in user_profiles[post_user_index]:
                        user_profiles[post_user_index] += update_profile
                    # If the profile has a recent post but it's not the user's
                    # latest, replace it
                    elif update_profile not in user_profiles[post_user_index]:
                        user_profiles[post_user_index] = user_profiles[
                            post_user_index].split(
                                "# Recent post:")[0] + update_profile
            except Exception:
                print("update previous post failed")

        # coarse filtering 4000 posts due to the memory constraint.
        filtered_posts_tuple = coarse_filtering(list(t_items.values()), 4000)
        corpus = user_profiles + filtered_posts_tuple[0]
        # corpus = user_profiles + list(t_items.values())
        tweet_vector_start_t = time.time()
        if use_openai_embedding:
            all_post_vector_list = generate_post_vector_openai(corpus,
                                                               batch_size=1000)
        else:
            all_post_vector_list = generate_post_vector(twhin_model,
                                                        twhin_tokenizer,
                                                        corpus,
                                                        batch_size=1000)
        tweet_vector_end_t = time.time()
        rec_log.info(
            f"twhin model cost time: {tweet_vector_end_t-tweet_vector_start_t}"
        )
        user_vector = all_post_vector_list[:len(user_profiles)]
        posts_vector = all_post_vector_list[len(user_profiles):]

        if enable_like_score:
            # Traverse all liked post ids, collecting liked post vectors from
            # posts_vector for matrix acceleration calculation
            like_posts_vectors = []
            for user_idx, like_post_ids in enumerate(like_post_ids_all):
                if len(like_post_ids) != 1:
                    for like_post_id in like_post_ids:
                        try:
                            like_posts_vectors.append(
                                posts_vector[like_post_id - 1])
                        except Exception:
                            like_posts_vectors.append(user_vector[user_idx])
                else:
                    like_posts_vectors += [
                        user_vector[user_idx] for _ in range(5)
                    ]
            try:
                like_posts_vectors = torch.stack(like_posts_vectors).view(
                    len(user_table), 5, posts_vector.shape[1])
            except Exception:
                import pdb  # noqa: F811
                pdb.set_trace()
        get_similar_start_t = time.time()
        cosine_similarities = cosine_similarity(user_vector, posts_vector)
        get_similar_end_t = time.time()
        rec_log.info(f"get cosine_similarity time: "
                     f"{get_similar_end_t-get_similar_start_t}")
        if enable_like_score:
            for user_index, profile in enumerate(user_profiles):
                user_like_posts_vector = like_posts_vectors[user_index]
                like_scores = calculate_like_similarity(
                    user_like_posts_vector, posts_vector)
                try:
                    scores = scores + like_scores
                except Exception:
                    import pdb
                    pdb.set_trace()

        filter_posts_index = filtered_posts_tuple[1]
        cosine_similarities = cosine_similarities * scores[filter_posts_index]
        cosine_similarities = torch.tensor(cosine_similarities)
        value, indices = torch.topk(cosine_similarities,
                                    max_rec_post_len,
                                    dim=1,
                                    largest=True,
                                    sorted=True)
        filter_posts_index = torch.tensor(filter_posts_index)
        indices = filter_posts_index[indices]
        # cosine_similarities = cosine_similarities * scores
        # cosine_similarities = torch.tensor(cosine_similarities)
        # value, indices = torch.topk(cosine_similarities,
        #                             max_rec_post_len,
        #                             dim=1,
        #                             largest=True,
        #                             sorted=True)

        matrix_list = indices.cpu().numpy()
        post_list = list(t_items.keys())
        for rec_ids in matrix_list:
            rec_ids = [post_list[i] for i in rec_ids]
            new_rec_matrix.append(rec_ids)

    return new_rec_matrix


def normalize_similarity_adjustments(post_scores, base_similarity,
                                     like_similarity, dislike_similarity):
    """
    Normalize the adjustments to keep them in scale with overall similarities.

    Args:
        post_scores (list): List of post scores.
        base_similarity (float): Base similarity score.
        like_similarity (float): Similarity score for liked posts.
        dislike_similarity (float): Similarity score for disliked posts.

    Returns:
        float: Adjusted similarity score.
    """
    if len(post_scores) == 0:
        return base_similarity

    max_score = max(post_scores, key=lambda x: x[1])[1]
    min_score = min(post_scores, key=lambda x: x[1])[1]
    score_range = max_score - min_score
    adjustment = (like_similarity - dislike_similarity) * (score_range / 2)
    return base_similarity + adjustment


def swap_random_posts(rec_post_ids, post_ids, swap_percent=0.1):
    """
    Swap a percentage of recommended posts with random posts.

    Args:
        rec_post_ids (list): List of recommended post IDs.
        post_ids (list): List of all post IDs.
        swap_percent (float): Percentage of posts to swap.

    Returns:
        list: Updated list of recommended post IDs.
    """
    num_to_swap = int(len(rec_post_ids) * swap_percent)
    posts_to_swap = random.sample(post_ids, num_to_swap)
    indices_to_replace = random.sample(range(len(rec_post_ids)), num_to_swap)

    for idx, new_post in zip(indices_to_replace, posts_to_swap):
        rec_post_ids[idx] = new_post

    return rec_post_ids


def get_trace_contents(user_id, action, post_table, trace_table):
    """
    Get the contents of posts that a user has interacted with.

    Args:
        user_id (str): ID of the user.
        action (str): Type of action (like or unlike).
        post_table (list): List of posts.
        trace_table (list): List of user interactions.

    Returns:
        list: List of post contents.
    """
    # Get post IDs from trace table for the given user and action
    trace_post_ids = [
        trace['post_id'] for trace in trace_table
        if (trace['user_id'] == user_id and trace['action'] == action)
    ]
    # Fetch post contents from post table where post IDs match those in the
    # trace
    trace_contents = [
        post['content'] for post in post_table
        if post['post_id'] in trace_post_ids
    ]
    return trace_contents


def rec_sys_personalized_with_trace(
    user_table: List[Dict[str, Any]],
    post_table: List[Dict[str, Any]],
    trace_table: List[Dict[str, Any]],
    rec_matrix: List[List],
    max_rec_post_len: int,
    swap_rate: float = 0.1,
) -> List[List]:
    """
    This version:
    1. If the number of posts is less than or equal to the maximum
        recommended length, each user gets all post IDs

    2. Otherwise:
        - For each user, get a like-trace pool and dislike-trace pool from the
            trace table
        - For each user, calculate the similarity between the user's bio and
            the post text
        - Use the trace table to adjust the similarity score
        - Swap 10% of the recommended posts with the random posts

    Personalized recommendation system that uses user interaction traces.

    Args:
        user_table (List[Dict[str, Any]]): List of users.
        post_table (List[Dict[str, Any]]): List of posts.
        trace_table (List[Dict[str, Any]]): List of user interactions.
        rec_matrix (List[List]): Existing recommendation matrix.
        max_rec_post_len (int): Maximum number of recommended posts.
        swap_rate (float): Percentage of posts to swap for diversity.

    Returns:
        List[List]: Updated recommendation matrix.
    """

    start_time = time.time()

    new_rec_matrix = []
    post_ids = [post['post_id'] for post in post_table]
    if len(post_ids) <= max_rec_post_len:
        new_rec_matrix = [post_ids] * (len(rec_matrix) - 1)
    else:
        for idx in range(1, len(rec_matrix)):
            user_id = user_table[idx - 1]['user_id']
            user_bio = user_table[idx - 1]['bio']
            # filter out posts that belong to the user
            available_post_contents = [(post['post_id'], post['content'])
                                       for post in post_table
                                       if post['user_id'] != user_id]

            # filter out like-trace and dislike-trace
            like_trace_contents = get_trace_contents(
                user_id, ActionType.LIKE_POST.value, post_table, trace_table)
            dislike_trace_contents = get_trace_contents(
                user_id, ActionType.UNLIKE_POST.value, post_table, trace_table)
            # calculate similarity between user bio and post text
            post_scores = []
            for post_id, post_content in available_post_contents:
                if model is not None:
                    user_embedding = model.encode(user_bio)
                    post_embedding = model.encode(post_content)
                    base_similarity = np.dot(
                        user_embedding,
                        post_embedding) / (np.linalg.norm(user_embedding) *
                                           np.linalg.norm(post_embedding))
                    post_scores.append((post_id, base_similarity))
                else:
                    post_scores.append((post_id, random.random()))

            new_post_scores = []
            # adjust similarity based on like and dislike traces
            for _post_id, _base_similarity in post_scores:
                _post_content = post_table[post_ids.index(_post_id)]['content']
                like_similarity = sum(
                    np.dot(model.encode(_post_content), model.encode(like)) /
                    (np.linalg.norm(model.encode(_post_content)) *
                     np.linalg.norm(model.encode(like)))
                    for like in like_trace_contents) / len(
                        like_trace_contents) if like_trace_contents else 0
                dislike_similarity = sum(
                    np.dot(model.encode(_post_content), model.encode(dislike))
                    / (np.linalg.norm(model.encode(_post_content)) *
                       np.linalg.norm(model.encode(dislike)))
                    for dislike in dislike_trace_contents) / len(
                        dislike_trace_contents
                    ) if dislike_trace_contents else 0

                # Normalize and apply adjustments
                adjusted_similarity = normalize_similarity_adjustments(
                    post_scores, _base_similarity, like_similarity,
                    dislike_similarity)
                new_post_scores.append((_post_id, adjusted_similarity))

            # sort posts by similarity
            new_post_scores.sort(key=lambda x: x[1], reverse=True)
            # extract post ids
            rec_post_ids = [
                post_id for post_id, _ in new_post_scores[:max_rec_post_len]
            ]

            if swap_rate > 0:
                # swap the recommended posts with random posts
                swap_free_ids = [
                    post_id for post_id in post_ids
                    if post_id not in rec_post_ids and post_id not in [
                        trace['post_id']
                        for trace in trace_table if trace['user_id']
                    ]
                ]
                rec_post_ids = swap_random_posts(rec_post_ids, swap_free_ids,
                                                 swap_rate)

            new_rec_matrix.append(rec_post_ids)
    end_time = time.time()
    print(f'Personalized recommendation time: {end_time - start_time:.6f}s')
    return new_rec_matrix
