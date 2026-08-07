import aiohttp
import asyncio
import json
import time

error_urls = []


# Read guild data from file
def read_guild_data(file_path=r'uaguildlist.txt'):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return [line.strip() for line in file.readlines()]
    except Exception as e:
        print(f"An error occurred while reading guild data: {e}")
        return []


# Read additional characters from file
def read_additional_characters(file_path=r'addCharacters.txt'):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            characters = []

            for line in file:
                parts = line.strip().split()

                if len(parts) >= 3:
                    region = parts[0]
                    name = parts[1]
                    realm = " ".join(parts[2:])

                    characters.append((region, realm, name))

            return characters

    except Exception as e:
        print(f"An error occurred while reading additional characters: {e}")
        return []


# Fetch data from URL
async def fetch_data(session, url):
    try:
        async with session.get(url) as response:
            return await response.json()

    except Exception as e:
        print(f"Error fetching data from {url}: {e}")
        error_urls.append(url)
        return None


# Process player
async def process_player(session, region, realm, name, data_dict):

    url = (
        f"http://raider.io/api/v1/characters/profile?"
        f"region={region}&realm={realm}&name={name}"
        f"&fields=mythic_plus_scores_by_season:current,class,active_spec_name"
    )

    player_data = await fetch_data(session, url)

    if player_data is None:
        return


    if player_data.get("statusCode") == 400:
        with open("400.txt", "a", encoding="utf-8") as error_file:
            error_file.write(
                f"Character not found: {name} from realm {realm}\n"
            )
        return


    scores = (
        player_data
        .get("mythic_plus_scores_by_season", [{}])[0]
        .get("scores", {})
    )


    old_data = data_dict.get((region, realm, name), {})


    data_dict[(region, realm, name)] = {

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



# Process guild
async def process_guild(session, url, data_dict):

    guild_data = await fetch_data(session, url)

    if guild_data is None:
        return


    if "members" not in guild_data:
        return


    region = guild_data.get("region", "eu")
    guild = guild_data.get("name")


    for member in guild_data.get("members", []):

        character = member.get("character", {})

        realm = character.get("realm")
        name = character.get("name")
        class_ = character.get("class")
        active_spec_name = character.get("active_spec_name")


        if name and realm:

            player_key = (region, realm, name)


            data_dict[player_key] = {

                "region": region,
                "realm": realm,
                "guild": guild,
                "name": name,

                "class": class_,
                "active_spec_name": active_spec_name
            }



# Main
async def main():

    with open("400.txt", "w", encoding="utf-8") as error_file:
        error_file.write("")


    data_dict = {}


    prefix = "http://raider.io/api/v1/guilds/profile?"
    postfix = "&fields=members"


    connector = aiohttp.TCPConnector(ssl=False)


    async with aiohttp.ClientSession(connector=connector) as session:


        # Guilds
        url_list = read_guild_data()


        for url in url_list:

            await process_guild(
                session,
                prefix + url + postfix,
                data_dict
            )



        # Additional characters

        additional_characters = read_additional_characters()


        for region, realm, name in additional_characters:

            data_dict[(region, realm, name)] = {

                "region": region,
                "realm": realm,
                "guild": None,
                "name": name,

                "class": None,
                "active_spec_name": None
            }



        # Player RIO data

        request_count = 0


        for region, realm, name in list(data_dict.keys()):


            await process_player(
                session,
                region,
                realm,
                name,
                data_dict
            )


            request_count += 1


            if request_count % 190 == 0:

                await asyncio.sleep(120)



        # Retry failed guild URLs

        for url in error_urls:

            await process_guild(
                session,
                prefix + url + postfix,
                data_dict
            )



    # Save JSON

    with open(
        r'members.json',
        'w',
        encoding='utf-8'
    ) as file:

        json.dump(
            list(data_dict.values()),
            file,
            ensure_ascii=False,
            indent=2
        )



# Run

start_time = time.time()

asyncio.run(main())

end_time = time.time()


print(
    f"Execution time: {end_time - start_time} seconds"
)