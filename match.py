#!/usr/bin/env python

import json
import os
import shlex
import subprocess
import sys
import tarfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import List, Optional

import requests


@dataclass
class Result:
    player_id: int
    rank: int
    last_frame_alive: int


@dataclass
class MatchResult:
    bot_name: str
    docker_image: str
    rank: int
    last_frame_alive: int
    error_log: Optional[str]


@dataclass
class Match:
    id: str
    date: str
    replay: str
    seed: int
    width: int
    height: int
    match_results: List[MatchResult]
    workflow_run_id: int


@dataclass
class Output:
    width: int
    height: int
    hlt_file: str
    seed: int
    results: List[Result]
    timeout_bots: List[int]
    timeout_logs: List[str]


def parse_output(result, num_bots) -> Output:
    lines = result.splitlines()

    [width, height] = [int(x) for x in lines.pop(0).split()]
    [hlt_file, seed] = lines.pop(0).split()

    results = [
        Result(*(int(part) - 1 for part in parts))
        for parts in (line.split() for line in lines[:num_bots])
    ]
    lines = lines[num_bots:]
    timeout_bots = []
    timeout_logs = []
    if lines:
        # timeouts
        timeout_bots = [int(player_id) - 1 for player_id in lines.pop(0).split()]
        timeout_logs = lines.pop(0).strip().split()

    return Output(
        width,
        height,
        os.path.relpath(hlt_file),
        int(seed),
        results,
        timeout_bots,
        timeout_logs,
    )


def run_match(bots, map_size, match_id) -> Match:
    args = []
    for bot in bots:
        args.extend(
            [
                f"docker run --rm -i --cpus='0.32' --network=none --memory=1g {bot['docker-image']}",
                bot["name"],
            ]
        )

    halite_command = ["halite", "-q", "-d", map_size, "-o", *args]
    print(shlex.join(halite_command), file=sys.stderr)
    stdout = subprocess.check_output(halite_command, universal_newlines=True)

    output = parse_output(stdout, len(bots))

    match_results = []

    for i, bot in enumerate(bots):
        result = output.results[i]
        error_log = None
        if result.player_id in output.timeout_bots:
            index = output.timeout_bots.index(result.player_id)
            error_log = os.path.relpath(output.timeout_logs[index])

        match_results.append(
            MatchResult(
                bot["name"],
                bot["docker-image"],
                result.rank + 1,
                result.last_frame_alive,
                error_log,
            )
        )

    workflow_run_id = int(os.environ.get("GITHUB_RUN_ID"), 0)

    return Match(
        match_id,
        datetime.now(timezone.utc).isoformat(),
        output.hlt_file,
        output.seed,
        output.width,
        output.height,
        match_results,
        workflow_run_id,
    )


def pull(bots):
    for bot in bots:
        print(shlex.join(["docker", "pull", bot["docker-image"]]), file=sys.stderr)
        subprocess.run(["docker", "pull", bot["docker-image"]], stdout=sys.stderr)


def main():
    match_id = sys.argv[1]
    map_size = sys.argv[2]
    bots = json.loads(sys.argv[3])

    pull(bots)
    match = run_match(bots, map_size, match_id)
    with open(f"{match.id}.json", "w") as match_output:
        json.dump(asdict(match), match_output)

    with tarfile.open(name=f"{match.id}.tar.xz", mode="x:xz") as tar:
        tar.add(match_output.name)
        tar.add(match.replay)
        for result in match.match_results:
            if result.error_log:
                tar.add(result.error_log)

    os.remove(match_output.name)
    os.remove(match.replay)
    for result in match.match_results:
        if result.error_log:
            os.remove(result.error_log)

    api_token = os.environ["API_TOKEN"]
    print(f"Uploading match result file {match.id}.tar.xz", file=sys.stderr)

    for i in range(5):
        r = requests.post(
            "https://halite-tournament.fly.dev/api/v1/match-result/",
            files={"result": open(f"{match.id}.tar.xz", "rb")},
            headers={"Authorization": f"Token {api_token}"},
        )
        if r.ok:
            break
        else:
            try:
                r.raise_for_status()
            except requests.HTTPError as e:
                if i >= 4 or r.status_code < 500:
                    raise

                print(f"Received error {e}, sleeping and retrying...")
                time.sleep(10)

    print(f"Upload complete", file=sys.stderr)


if __name__ == "__main__":
    main()
