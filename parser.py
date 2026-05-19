import aiohttp
import asyncio
import json
import time

error_urls = []  # List to store URLs that returned errors during requests

# Function to read guild data from the file
def read_guild_data(file_path=r'uaguildlist.txt'):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return [line.strip() for line in file.readlines()]
    except Exception as e:
        print(f"An error occurred while reading guild data: {e}")
        return []

# Function to read additional characters from a file
def read_additional_characters(file_path=r'addCharacters.txt'):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            characters = []
            for line in file:
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0]
                    realm = " ".join(parts[1:])  # Якщо сервер складається з кількох слів
                    characters.append((realm, name))
            return characters
    except Exception as e:
        print(f"An error occurred while reading additional characters: {e}")
        return []

# Asynchronous function to fetch data from a given URL
async def fetch_data(session, url):
    try:
        async with session.get(url) as response:
            return await response.json()
    except Exception as e:
        print(f"Error fetching data from {url}: {e}")
        error_urls.append(url)
        return None

# Asynchronous function to process a player and fetch their RIO data
async def process_player(session, realm, name, data_dict):
    url = f"http://raider.io/api/v1/characters/profile?region=eu&realm={realm}&name={name}&fields=mythic_plus_scores_by_season:current,class,active_spec_name"
    player_data = await fetch_data(session, url)

    if player_data is not None:
        if 'statusCode' in player_data and player_data['statusCode'] == 400:
            with open("400.txt", "a", encoding="utf-8") as error_file:
                error_file.write(f"Character not found: {name} from realm {realm}\n")
            return

        # Отримуємо основні дані персонажа
        class_ = player_data.get('class', None)
        active_spec_name = player_data.get('active_spec_name', None)

        # Отримуємо M+ оцінки
        scores = player_data.get('mythic_plus_scores_by_season', [{}])[0].get('scores', {})
        rio_all = scores.get('all', 0)
        rio_dps = scores.get('dps', 0)
        rio_healer = scores.get('healer', 0)
        rio_tank = scores.get('tank', 0)
        spec_0 = scores.get('spec_0', 0)
        spec_1 = scores.get('spec_1', 0)
        spec_2 = scores.get('spec_2', 0)
        spec_3 = scores.get('spec_3', 0)

        # Оновлюємо дані у словнику
        data_dict[(realm, name)] = {
            'realm': realm,
            'guild': data_dict.get((realm, name), {}).get('guild', None),
            'name': name,
            'class': class_,
            'active_spec_name': active_spec_name,
            'rio_all': rio_all,
            'rio_dps': rio_dps,
            'rio_healer': rio_healer,
            'rio_tank': rio_tank,
            'spec_0': spec_0,
            'spec_1': spec_1,
            'spec_2': spec_2,
            'spec_3': spec_3,
        }

# Asynchronous function to process a guild and fetch its members
async def process_guild(session, url, data_dict):
    guild_data = await fetch_data(session, url)
    if 'members' in guild_data:
        for member in guild_data.get('members', []):
            realm = member.get('character', {}).get('realm')
            guild = guild_data.get('name')
            name = member.get('character', {}).get('name')
            class_ = member.get('character', {}).get('class')
            active_spec_name = member.get('character', {}).get('active_spec_name')

            if name and class_:
                player_key = (realm, name)
                data_dict[player_key] = {
                    'realm': realm, 'guild': guild, 'name': name,
                    'class': class_, 'active_spec_name': active_spec_name
                }

# Main function to coordinate fetching and processing data
async def main():
    with open("400.txt", "w", encoding="utf-8") as error_file:
        error_file.write("")

    data_dict = {}  # Dictionary to store player data
    prefix = "http://raider.io/api/v1/guilds/profile?region=eu&"
    postfix = "&fields=members"

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Process guilds
        url_list = read_guild_data()
        request_count = 0
        for url in url_list:
            await process_guild(session, prefix + url + postfix, data_dict)

        # Read and add additional characters
        additional_characters = read_additional_characters()
        for realm, name in additional_characters:
            data_dict[(realm, name)] = {
                'realm': realm, 'guild': None, 'name': name,
                'class': None, 'active_spec_name': None
            }

        # Fetch RIO data for all players
        for player_key in data_dict.keys():
            realm, name = player_key
            await process_player(session, realm, name, data_dict)
            request_count += 1
            if request_count % 190 == 0:                
                await asyncio.sleep(2 * 60)  # Pause for 2 minutes
        
        # Retry failed URLs
        for url in error_urls:
            await process_guild(session, prefix + url + postfix, data_dict)

    # Save results to JSON
    with open(r'members.json', 'w', encoding='utf-8') as file:
        json.dump(list(data_dict.values()), file, ensure_ascii=False, indent=2)

# Measure the execution time
start_time = time.time()
asyncio.run(main())
end_time = time.time()
print(f"Execution time: {end_time - start_time} seconds")
