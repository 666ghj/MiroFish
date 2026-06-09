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
import os
import re
import sys
from pathlib import Path
from typing import List


# The license template file is hard-coded with specific start and end lines
def fine_license_start_line(lines: List[str], start_with: str) -> int:
    for i in range(len(lines)):
        if lines[i].startswith(start_with):
            return i
    return None


def find_license_end_line(lines: List[str], start_with: str) -> int:
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith(start_with):
            return i
    return None


def update_license_in_file(
    file_path: str,
    license_template_path: str,
    start_line_start_with: str,
    end_line_start_with: str,
) -> bool:
    with open(file_path, 'r',
              encoding='utf-8') as f:  # for windows compatibility
        content = f.read()

    with open(license_template_path, 'r', encoding='utf-8') as f:
        new_license = f.read().strip()

    maybe_existing_licenses = re.findall(r'^#.*?(?=\n)', content,
                                         re.MULTILINE | re.DOTALL)
    start_index = fine_license_start_line(maybe_existing_licenses,
                                          start_line_start_with)
    end_index = find_license_end_line(maybe_existing_licenses,
                                      end_line_start_with)
    if start_index is not None and end_index is not None:
        maybe_existing_licenses = maybe_existing_licenses[
            start_index:end_index + 1]
    else:
        maybe_existing_licenses = None
    if maybe_existing_licenses:
        maybe_old_licenses = '\n'.join(maybe_existing_licenses)
        if maybe_old_licenses.strip() != new_license.strip():
            replaced_content = content.replace(maybe_old_licenses, new_license)
            with open(file_path, 'w') as f:
                f.write(replaced_content)
            print(f'Replaced license in {file_path}')
            return True
        else:
            return False
    else:
        with open(file_path, 'w') as f:
            f.write(new_license + '\n' + content)
        print(f'Added license to {file_path}')
        return True


def update_license_in_directory(
    directory_path: str,
    license_template_path: str,
    start_line_start_with: str,
    end_line_start_with: str,
) -> None:
    # Check if directory exists
    if not os.path.isdir(directory_path):
        raise NotADirectoryError(f'{directory_path} is not a directory')
    # Check if license template exists
    if not os.path.isfile(license_template_path):
        raise FileNotFoundError(f'{license_template_path} not found')

    file_count = 0
    for py_files in Path(directory_path).rglob("*.py"):
        if py_files.name.startswith('.'):
            continue
        if any(part.startswith('.') for part in py_files.parts):
            continue
        if update_license_in_file(
                py_files,
                license_template_path,
                start_line_start_with,
                end_line_start_with,
        ):
            file_count += 1

    print(f'License updated in {file_count} files')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(
            "Usage from command line: "
            "python update_license.py <directory_path> <license_template_path>"
            "No valid input arguments found, please enter manually.")
        directory_path = input("Enter directory path: ")
        license_template_path = input("Enter license template path: ")
    else:
        directory_path = sys.argv[1]
        license_template_path = sys.argv[2]

    start_line_start_with = "# =========== Copyright"
    end_line_start_with = "# =========== Copyright"
    update_license_in_directory(
        directory_path,
        license_template_path,
        start_line_start_with,
        end_line_start_with,
    )
