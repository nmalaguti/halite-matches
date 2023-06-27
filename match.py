#!/usr/bin/env python

import json
import os
import subprocess
import sys
import shlex


def main():
    map_size = sys.argv[1]
    bot_info = json.loads(sys.argv[2])

    for bot in bot_info:
        print(shlex.join(["docker", "pull", bot["docker-image"]]))
        subprocess.run(["docker", "pull", bot["docker-image"]], check=True)

    args = []
    for bot in bot_info:
        args.extend([f"docker run --rm -i -c=1024 {bot['docker-image']}", bot["name"]])

    halite_command = ["halite", "-d", map_size, "-o", *args]
    print(shlex.join(halite_command))
    os.execvp(halite_command[0], halite_command)


if __name__ == "__main__":
    main()
