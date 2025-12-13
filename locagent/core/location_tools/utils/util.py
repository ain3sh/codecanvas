import os
import fnmatch
import re


GRAPH_INDEX_DIR = os.environ.get("GRAPH_INDEX_DIR")
BM25_INDEX_DIR = os.environ.get("BM25_INDEX_DIR")
assert GRAPH_INDEX_DIR != ''
assert BM25_INDEX_DIR != ''


def find_matching_files_from_list(file_list, file_pattern):
    """
    Find and return a list of file paths from the given list that match the given keyword or pattern.
    """
    if '*' in file_pattern or '?' in file_pattern or '[' in file_pattern:
        matching_files = fnmatch.filter(file_list, file_pattern)
    else:
        matching_files = [file for file in file_list if file_pattern in file]
    return matching_files


def merge_intervals(intervals):
    if not intervals:
        return []
    intervals.sort(key=lambda interval: interval[0])
    merged_intervals = [intervals[0]]
    for current in intervals[1:]:
        last = merged_intervals[-1]
        if current[0] <= last[1]:
            merged_intervals[-1] = (last[0], max(last[1], current[1]))
        else:
            merged_intervals.append(current)
    return merged_intervals


def extract_file_to_code(raw_content: str):
    pattern = r'([\w\/\.]+)\n```\n(.*?)\n```'
    matches = re.findall(pattern, raw_content, re.DOTALL)
    file_to_code = {filename: code for filename, code in matches}
    return file_to_code
