import aiohttp
import asyncio
import json
import os
import time
from urllib.parse import parse_qs

BASE = os.environ.get("RIO_BASE", "https://raider.io")
RETRY_DELAYS = [5, 20, 60]          # пауза (сек) перед повторними спробами
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_CONSECUTIVE_FAILURES = 25       # стільки невдач підряд = raider.io лежить, запуск скасовується
MEMBERS_FILE = "members.json"

consecutive_failures = 0
failed_guilds = set()   # гільдії, які не вдалося завантажити (щоб зберегти старих учасників)
OLD_DATA = {}           # попередній members.json


def read_guild_data(file_path='uaguildlist.txt'):
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as file:
            return [line.strip() for line in file if line.strip()]
    except Exception as e:
        print(f"An error occurred while reading guild data: {e}")
        return []


def read_additional_characters(file_path='addCharacters.txt'):
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as file:
            characters = []
            for line in file:
                parts = line.strip().split()
                if len(parts) >= 3:
                    characters.append((parts[0], " ".join(parts[2:]), parts[1]))
            return characters
    except Exception as e:
        print(f"An error occurred while reading additional characters: {e}")
        return []


def load_old_data():
    try:
        with open(MEMBERS_FILE, 'r', encoding='utf-8') as f:
            return {(m["region"], m["realm"], m["name"]): m for m in json.load(f)}
    except Exception:
        return {}


async def fetch_data(session, url):
    """GET з повторами. 429/5xx і мережеві помилки повторюються, потім повертається None."""
    global consecutive_failures
    last_error = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            async with session.get(url) as response:
                if response.status in RETRY_STATUSES:
                    last_error = f"HTTP {response.status}"
                else:
                    data = await response.json(content_type=None)
                    consecutive_failures = 0
                    return data
        except Exception as e:
            last_error = str(e)
        if attempt < len(RETRY_DELAYS):
            await asyncio.sleep(RETRY_DELAYS[attempt])
    consecutive_failures += 1
    print(f"Failed after retries ({last_error}): {url}")
    return None


async def process_player(session, region, realm, name, data_dict):
    key = (region, realm, name)
    url = (
        f"{BASE}/api/v1/characters/profile?"
        f"region={region}&realm={realm}&name={name}"
        f"&fields=mythic_plus_scores_by_season:current,class,active_spec_name"
    )
    player_data = await fetch_data(session, url)

    if player_data is None:
        # не вдалося отримати: беремо старі значення, щоб не втратити персонажа
        old = OLD_DATA.get(key)
        if old:
            for field, value in old.items():
                if data_dict[key].get(field) is None:
                    data_dict[key][field] = value
        return

    if player_data.get("statusCode") == 400:
        with open("400.txt", "a", encoding="utf-8") as error_file:
            error_file.write(f"Character not found: {name} from realm {realm}\n")
        return

    seasons = player_data.get("mythic_plus_scores_by_season") or [{}]
    scores = seasons[0].get("scores", {})
    old_data = data_dict.get(key, {})

    data_dict[key] = {
        "region": region,
        "realm": realm,
        "guild": old_data.get("guild"),
        "name": name,
        "class": player_data.get("class"),
        "active_spec_name": player_data.get("active_spec_name"),
        "rio_all": scores.get("all", 0),
        "rio_dps": scores.get("dps", 0),
        "rio_healer": scores.get("healer", 0),
        "rio_tank": scores.get("tank", 0),
        "spec_0": scores.get("spec_0", 0),
        "spec_1": scores.get("spec_1", 0),
        "spec_2": scores.get("spec_2", 0),
        "spec_3": scores.get("spec_3", 0),
    }


async def process_guild(session, guild_line, data_dict):
    url = f"{BASE}/api/v1/guilds/profile?{guild_line}&fields=members"
    guild_data = await fetch_data(session, url)

    if guild_data is None:
        name = parse_qs(guild_line).get("name", [""])[0]
        failed_guilds.add(name.lower())
        return

    if "members" not in guild_data:
        return  # напр. "Could not find requested guild" - гільдії немає на raider.io

    region = guild_data.get("region", "eu")
    guild = guild_data.get("name")

    for member in guild_data.get("members", []):
        character = member.get("character", {})
        realm = character.get("realm")
        name = character.get("name")
        if name and realm:
            data_dict[(region, realm, name)] = {
                "region": region,
                "realm": realm,
                "guild": guild,
                "name": name,
                "class": character.get("class"),
                "active_spec_name": character.get("active_spec_name"),
            }


async def main():
    global OLD_DATA
    OLD_DATA = load_old_data()

    with open("400.txt", "w", encoding="utf-8") as error_file:
        error_file.write("")

    data_dict = {}

    async with aiohttp.ClientSession() as session:
        for guild_line in read_guild_data():
            await process_guild(session, guild_line, data_dict)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print("raider.io недоступний, запуск скасовано, members.json не змінено")
                return

        for region, realm, name in read_additional_characters():
            data_dict[(region, realm, name)] = {
                "region": region, "realm": realm, "guild": None,
                "name": name, "class": None, "active_spec_name": None,
            }

        request_count = 0
        for region, realm, name in list(data_dict.keys()):
            try:
                await process_player(session, region, realm, name, data_dict)
            except Exception as e:
                print(f"Unexpected error for {name}-{realm}: {e}")

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print("raider.io недоступний, запуск скасовано, members.json не змінено")
                return

            request_count += 1
            if request_count % 190 == 0:
                await asyncio.sleep(120)

    # гільдії, які не завантажились: лишаємо їхніх старих учасників
    for key, old in OLD_DATA.items():
        if key not in data_dict and (old.get("guild") or "").lower() in failed_guilds:
            data_dict[key] = old

    # атомарний запис: бот ніколи не побачить напівзаписаний файл
    tmp = MEMBERS_FILE + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as file:
        json.dump(list(data_dict.values()), file, ensure_ascii=False, indent=2)
    os.replace(tmp, MEMBERS_FILE)
    print(f"Saved {len(data_dict)} members; failed guilds: {sorted(failed_guilds)}")


start_time = time.time()
asyncio.run(main())
print(f"Execution time: {time.time() - start_time} seconds")