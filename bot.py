import json
import discord
import aiohttp
import asyncio
import re
from discord import app_commands
from config import token

# Initialize intents and client
intents = discord.Intents.all()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Function to read guild data from the file
def read_guild_data(file_path='uaguildlist.txt'):
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as file:
            lines = file.readlines()
            return [line.strip() for line in lines if line.strip()]
    except Exception as e:
        print(f"An error occurred while reading guild data: {e}")
        return []

# Asynchronous function to fetch guild data
async def fetch_guild_data(guild_url, tier):
    prefix = "http://raider.io/api/v1/guilds/profile?"
    postfix = "&fields=raid_rankings,raid_progression"
    
    switch_dict = {
        1: "nerubar-palace",
        2: "liberation-of-undermine",
        3: "manaforge-omega"
    }
    raid = switch_dict.get(tier)
    
    current_bosses_names = {
        1: "plexus-sentinel",
        2: "soulbinder-naazindhri",
        3: "loomithar",
        4: "forgeweaver-araz",
        5: "fractillus",
        6: "the-soul-hunters",
        7: "nexus-king-salhadaar",
        8: "dimensius"
    }
    
    boss_kill_url_suffix = {
        "M": "&difficulty=mythic",
        "H": "&difficulty=heroic",
        "N": "&difficulty=normal",
    }

    try:
        async with aiohttp.ClientSession() as session:            
            async with session.get(prefix + guild_url + postfix, ssl=False) as response:
                json_data = await response.json()

                if not all(key in json_data for key in ['name', 'realm', 'raid_progression', 'raid_rankings']):
                    print(f"Invalid API response format for {guild_url}: {json_data}")
                    return None

                guild_name = json_data['name']
                guild_realm = json_data['realm']
                guild_progress = json_data['raid_progression'][raid].get('summary', '0/0 N')
                guild_rank = json_data['raid_rankings'][raid]['mythic'].get('world', None)
                
                best_percent = 100.0
                pull_count = 0
                
                try:
                    current_progress = int(guild_progress.split("/")[0])
                    if current_progress < 8:
                        next_boss = current_bosses_names.get(current_progress + 1)
                        if not next_boss:
                            raise ValueError("Invalid boss number")
                         
                        region, realm, guild = guild_url.split("&")
                        formatted_region = region.replace("region=", "")
                        formatted_realm = realm.replace("%20", "-").replace("realm=", "")
                        formatted_guild = guild.replace("name=", "guild=")
                        
                        difficulty = guild_progress[-1]
                        boss_kill_url = (
                            f"https://raider.io/api/guilds/boss-kills?raid={raid}"
                            f"{boss_kill_url_suffix.get(difficulty, '')}&region={formatted_region}&realm={formatted_realm}&{formatted_guild}&boss={next_boss}"
                        )
                        
                        async with session.get(boss_kill_url, ssl=False) as boss_response:
                            if boss_response.status != 422:                                  
                                boss_data = await boss_response.json()
                                kill_details = boss_data.get('killDetails', {}).get('attempt', {})
                                best_percent = kill_details.get('bestPercent', 100.0)
                                pull_count = kill_details.get('pullCount', 0)                            
                except Exception as e:
                    print(f"Error processing guild progress for {guild_name}: {e}")
                
                return {                    
                    "name": guild_name,
                    "realm": guild_realm,
                    "progress": guild_progress,
                    "rank": guild_rank,
                    "best_percent": best_percent,
                    "pull_count": pull_count
                }

    except Exception as e:
        print(f"An error occurred while fetching guild data for {guild_url}: {e}")
        return None

# Function to send long messages in chunks
async def send_long_message(interaction, message, chunk_size=2000):
    # Split the message into chunks of the specified size
    message_chunks = []
    current_chunk = ""

    for line in message.splitlines():
        if len(current_chunk) + len(line) + 1 > chunk_size:
            message_chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += line + "\n"
    
    if current_chunk:
        message_chunks.append(current_chunk)

    # Send each chunk
    for chunk in message_chunks:
        await interaction.followup.send(chunk)
       
# Function to print guild ranks
async def print_guild_ranks(interaction, tier, limit):
    try:
        # Defer the response to indicate that the bot is processing the request
        await interaction.response.defer()

        # Asynchronously get data for all guilds of the specified tier
        url_list = read_guild_data()
        guilds = await asyncio.gather(*[fetch_guild_data(guild_url, tier) for guild_url in url_list])
        guilds = [guild for guild in guilds if guild]

        if not guilds:
            await interaction.followup.send(f"At the moment, there are no guilds with progression in the {tier} season.")
            return

        # Universal sorting by difficulty and progression, then by rank
        def custom_sort_key(guild):
            progression, difficulty = guild["progress"].split(" ")
            difficulty_order = {'M': 0, 'H': 1, 'N': 2}
            progression_number = int(progression.split('/')[0])
            return (difficulty_order.get(difficulty, 3), -progression_number, guild["rank"])

        # Sort guilds using the universal rule
        sorted_guilds = sorted(guilds, key=custom_sort_key)

        if limit != 'all':
            limit = int(limit)
            sorted_guilds = sorted_guilds[:limit]

        # Format guild data for output
        formatted_guilds = []
        for i, guild in enumerate(sorted_guilds):
            # Format basic fields
            guild_info = [f"{i + 1}. {guild['name']}, {guild['realm']}, {guild['progress']}, {guild['rank']} rank"]

            # Append best_percent and pull_count only if the conditions are met
            if not (guild["best_percent"] == 100):
                guild_info.append(f"{guild['best_percent']}% best")
            if not (guild["pull_count"] == 0 or guild["pull_count"] == None):
                guild_info.append(f"{guild['pull_count']} pulls")

            # Join all parts into a single line
            formatted_guilds.append(", ".join(guild_info))

        # Send the formatted guilds using send_long_message
        await send_long_message(interaction, "\n".join(formatted_guilds))

    except Exception as e:
        print(f"An error occurred while printing guild ranks: {e}")
        if interaction.response.is_done():
            await interaction.followup.send("An error occurred while processing the request. Please try again later.")
        else:
            await interaction.response.send_message("An error occurred while processing the request. Please try again later.")

# Command to print guilds raid ranks in the current addon
@tree.command(name="guilds", description="Guilds Raid Rank")
@app_commands.describe(
    season="1/2/3",
    limit="Number of guilds to display (or 'all' for full list)"
)
async def get_data(interaction, season: int = 3, limit: str = '10'):
    await print_guild_ranks(interaction, season, limit)

# Command to print player ranks in the current M+ season
@tree.command(name="rank", description="Guilds Mythic+ Rank")
@app_commands.describe(
    top="1-50",
    guilds="all/Нехай Щастить/... several guilds can be entered through ','.", 
    classes="all/death knight/death knight:3/... ':3' means you want to specify the spec.", 
    role="all/dps/healer/tank", 
    rio="0-3500"
)
async def rank(interaction, top: int = 10, classes: str = "all", guilds: str = "all", role: str = "all", rio: int = 2000):
    try:
        # Defer the response to indicate processing
        await interaction.response.defer()

        # Read data from the JSON file
        with open('members.json', 'r', encoding='utf-8') as file:
            members_data = json.load(file)

        # Checking the existence of data in the file
        if not members_data:
            await interaction.followup.send("No data to process. Complete the 'members.json' file before using this command.")
            return

        # Check for valid guild
        if guilds.lower() != "all":
            input_guilds = [g.strip().lower() for g in guilds.split(',')]
            members_data = [
                member for member in members_data
                if (
                    (member.get('guild') is None and 'none' in input_guilds) or
                    ((member.get('guild') or "").lower() in input_guilds)
                )
            ]
            if not members_data:
                await interaction.followup.send(
                    "No members found for the given guild(s). Check the spelling or try different values."
                )
                return
        
        # Check for valid class
        spec_number = 0
        valid_classes = {"all", "death knight", "demon hunter", "druid", "evoker", "hunter", "mage", "monk", "paladin", "priest", "rogue", "shaman", "warlock", "warrior"}
        if ':' in classes.lower():
            split_result = classes.split(':')            
            if len(split_result) == 2 and split_result[1].isdigit() and 1 <= int(split_result[1]) <= 4:
                classes = split_result[0]
                spec_number = int(split_result[1])                
                role = "all"
            else:
                await interaction.followup.send("Wrong class format. Use the valid format: death knight:3 or warrior:1.")
                return
        else:            
            if (classes or "").lower() not in valid_classes:
                await interaction.followup.send(f"Class '{classes}' does not exist. Use the valid classes: all, death knight, demon hunter, druid, evoker, hunter, mage, monk, paladin, priest, rogue, shaman, warlock, warrior.")
                return        

        # Check for valid role
        valid_roles = {"all", "dps", "healer", "tank"}
        if role.lower() not in valid_roles:
            await interaction.followup.send(f"Role '{role}' does not exist. Use the valid roles: all, dps, healer, tank or spec name.")
            return

        # Check if top value is within the range of 1 to 50 inclusive
        if not 1 <= top <= 50:
            await interaction.followup.send("Error: The value of top must be between 1 and 50 inclusive.")
            return
            
        # Check if rio value is within the range of 0 to 3500 inclusive
        if not 0 <= rio <= 3500:
            await interaction.followup.send("Error: The value of rio must be between 0 and 3500 inclusive.")
            return

        # Filter by class        
        if (classes or "").lower() != "all":
            members_data = [member for member in members_data if (member.get('class') or "").lower() == classes.lower()]

        # Check whether the specification is entered
        if spec_number == 0:
            # Sort by RIO rating according to the role
            if role.lower() != "all":
                members_data = sorted(members_data, key=lambda x: max(x.get('rio_' + role.lower(), 0), 0), reverse=True)
            else:
                members_data = sorted(members_data, key=lambda x: max(x.get('rio_all', 0), 0), reverse=True)

            # Filter by rio
            members_data = [member for member in members_data if max(member.get('rio_' + role.lower(), 0), 0) > rio]
        else:
            spec = str(spec_number - 1)
            # Sort by RIO rating according to the role
            members_data = sorted(members_data, key=lambda x: max(x.get('spec_' + spec, 0), 0), reverse=True)

            # Filter by rio
            members_data = [member for member in members_data if max(member.get('spec_' + spec, 0), 0) > rio]

        # Limit the number of displayed results
        members_data = members_data[:top]

        # Format header message
        header_message = f"Top {top} | Classes -> {classes} | Guilds -> {guilds} | Role -> {role} | Rio > {rio}"

        # Format and send the results
        if spec_number == 0:
            result_message = "\n".join([f"{i + 1}. {member['name']} ({member['guild']}, {member['realm']}) - {member['active_spec_name']} {member['class']} - RIO {role}: {member['rio_' + role.lower()]}" for i, member in enumerate(members_data)])
        else:
            result_message = "\n".join([f"{i + 1}. {member['name']} ({member['guild']}, {member['realm']}) - {member['active_spec_name']} {member['class']} - RIO {role}: {member['spec_' + spec]}" for i, member in enumerate(members_data)])

        # Send the follow-up message after the processing is done
        await send_long_message(interaction, header_message + "\n------------------------------------------------------------\n" + result_message)

    except Exception as e:
        print(f"An error occurred while processing the rank command: {e}")
        await interaction.followup.send("An error occurred while processing the command. Please try again later.")
            
@tree.command(name="tournament", description="Get top players in a guild for a tournament")
@app_commands.describe(
    guild="Guild name for the tournament",
    top="Number of players to display (default: 5)",
    format="Data source format: new or old (default: new)"
)
async def tournament(interaction, guild: str = "Нехай Щастить", top: int = 5, format: str = "new"):
    # Determine the data source based on the 'format' parameter
    if format == "new":
        data_file = 'tournament.json'
        filter_guild = False
    elif format == "old":
        data_file = 'members.json'
        filter_guild = True
    else:
        await interaction.response.send_message("Invalid format. Please use 'new' or 'old'.", ephemeral=True)
        return

    # Read data from the selected JSON file
    with open(data_file, 'r', encoding='utf-8') as file:
        members_data = json.load(file)

    # Checking the existence of data in the file
    if not members_data:
        await interaction.response.send_message(f"No data to process in '{data_file}'.", ephemeral=True)
        return

    if filter_guild:
        # Filter by guild if needed
        guild_members = [member for member in members_data if member['guild'].lower() == guild.lower()]

        if not guild_members:
            await interaction.response.send_message(f"No data available for the guild '{guild}'.", ephemeral=True)
            return
    else:
        # Use all members from the file
        guild_members = members_data

    # Define desired specs for melee and ranged DPS
    melee_specs = ["frost", "unholy", "havoc", "feral", "survival", "windwalker", "retribution", "assassination", "outlaw", "subtlety", "enhancement", "arms", "fury"]
    ranged_specs = ["balance", "augmentation", "devastation", "beast mastery", "marksmanship", "arcane", "fire", "frost", "shadow", "elemental", "affliction", "demonology", "destruction"]

    # Get top players for each category
    top3_tank = sorted(
        [member for member in guild_members if member.get('rio_tank', 0) >= 1000],
        key=lambda x: max(x.get('rio_tank', 0), 0),
        reverse=True
    )[:top]
    top3_healer = sorted(
        [member for member in guild_members if member.get('rio_healer', 0) >= 1000],
        key=lambda x: max(x.get('rio_healer', 0), 0),
        reverse=True
    )[:top]
    top3_mdd = sorted([member for member in guild_members if member.get('active_spec_name') and member['active_spec_name'].lower() in melee_specs and member['class'] != 'Mage'], key=lambda x: max(x.get('rio_dps', 0), 0), reverse=True)[:top]
    top3_rdd = sorted([member for member in guild_members if member.get('active_spec_name') and member['active_spec_name'].lower() in ranged_specs and member['class'] != 'Death Knight'], key=lambda x: max(x.get('rio_dps', 0), 0), reverse=True)[:top]

    # Send initial response to acknowledge the command
    await interaction.response.send_message(f"Top {top} Players for the Tournament:")

    # Create and send messages for each category separately
    categories = [
        ("Tanks", top3_tank, "rio_tank"),
        ("Healers", top3_healer, "rio_healer"),
        ("Melee DPS", top3_mdd, "rio_dps"),
        ("Ranged DPS", top3_rdd, "rio_dps"),
    ]

    for category_name, top_players, rating_key in categories:
        result_message = f"\n{category_name}:\n"
        for i, member in enumerate(top_players):
            if format == "new":
                result_message += f"{i + 1}. {member['name']} ({member['guild']}) - {member['active_spec_name']} {member['class']} - {member.get(rating_key, 'N/A')}\n"
            else:
                result_message += f"{i + 1}. {member['name']} - {member['active_spec_name']} {member['class']} - {member.get(rating_key, 'N/A')}\n"

        # Split the result message into chunks and send each part
        max_message_length = 2000
        for i in range(0, len(result_message), max_message_length):
            chunk = result_message[i:i + max_message_length]
            await interaction.followup.send(chunk)
       
from collections import defaultdict
import discord
from discord import app_commands

@tree.command(name="uwf", description="Ukrainian WoW First ranks")
@app_commands.describe(
    mode="df | tww | champs | stats"
)
async def uwf(
    interaction: discord.Interaction,
    mode: str | None = None
):
    await interaction.response.defer()

    with open("uwf.txt", "r", encoding="utf-8") as file:
        lines = file.readlines()

    # -------------------------
    # Parsing state
    # -------------------------
    current_expansion = None
    current_season = None
    rank_counter = 0

    data = []  # structured data
    guild_stats = defaultdict(list)
    champs_counter = defaultdict(int)

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        # Expansion
        if stripped in {"Dragonflight", "The War Within"}:
            current_expansion = stripped
            continue

        # Season
        if stripped.startswith("Season"):
            current_season = stripped
            rank_counter = 0
            continue

        # Guild line
        rank_counter += 1

        guild_name = stripped.split(",")[0]

        entry = {
            "expansion": current_expansion,
            "season": current_season,
            "rank": rank_counter,
            "text": stripped,
            "guild": guild_name
        }

        data.append(entry)
        guild_stats[guild_name].append(rank_counter)

        if rank_counter == 1:
            champs_counter[guild_name] += 1

    # -------------------------
    # MODE HANDLING
    # -------------------------
    output = []

    if mode is None:
        # FULL LIST
        output.append("## Dragonflight")
        output += build_expansion(data, "Dragonflight")

        output.append("\n## The War Within")
        output += build_expansion(data, "The War Within")

    elif mode.lower() == "df":
        output.append("## Dragonflight")
        output += build_expansion(data, "Dragonflight")

    elif mode.lower() == "tww":
        output.append("## The War Within")
        output += build_expansion(data, "The War Within")

    elif mode.lower() == "champs":
        output.append("## 🏆 Champions")

        sorted_champs = sorted(
            champs_counter.items(),
            key=lambda x: (-x[1], sum(guild_stats[x[0]]) / len(guild_stats[x[0]]))
        )

        output.append("```")
        for i, (guild, wins) in enumerate(sorted_champs, 1):
            output.append(f"{str(i).rjust(2)}. {guild} — {wins} wins")
        output.append("```")

    elif mode.lower() == "stats":
        output.append("## 📊 Guild statistics")

        sorted_stats = sorted(
            guild_stats.items(),
            key=lambda x: (-len(x[1]), min(x[1]))
        )

        output.append("```")
        for i, (guild, ranks) in enumerate(sorted_stats, 1):
            output.append(
                f"{str(i).rjust(2)}. {guild} — {len(ranks)} entries | best rank: {min(ranks)}"
            )
        output.append("```")

    else:
        await interaction.followup.send("Unknown mode.")
        return

    await send_long_message(interaction, "\n".join(output))

def build_expansion(data, expansion_name):
    result = []
    current_season = None
    counter = 0
    in_block = False

    for entry in data:
        if entry["expansion"] != expansion_name:
            continue

        if entry["season"] != current_season:
            if in_block:
                result.append("```")
                in_block = False

            current_season = entry["season"]
            counter = 0
            result.append(f"**{current_season}**")

        if not in_block:
            result.append("```")
            in_block = True

        counter += 1
        result.append(f"{str(counter).rjust(2)}. {entry['text']}")

    if in_block:
        result.append("```")

    return result
        
# Command "About us"
@tree.command(name="about_us", description="About us")
async def about_us(interaction):    
    await interaction.response.send_message("https://youtu.be/xvpVTd1gt5Q")
    
# Command "Rules"
@tree.command(name="rules", description="Rules")
async def rules(interaction):
    await interaction.response.send_message("https://cdn.discordapp.com/attachments/786720808788688918/1202356554523742289/image.png?ex=65e8d84d&is=65d6634d&hm=dee787e24cb77005a58568556547af37a24fe98bfcb11c1f6ecabc1bf72842ff&")
    
# Command "Help"
@tree.command(name="help", description="Get information about available commands")
async def help_command(interaction):
    try:
        help_message = (
            "**Available Commands:**\n"
            "\n/guilds - Get guild raid ranks in the current addon.\n"
            "       -season: Season number (1, 2, or 3, default is 3).\n"
            
            "\n/rank - Get player ranks in the current M+ season.\n"            
            "       -top: Number of top players to display (1-50, default is 10).\n"
            "       -guilds: Guilds to filter (all, guild names separated by ',').\n"
            "       -classes: Player classes to filter (all or specific class).\n"
            "       -role: Player role to filter (all, dps, healer, tank, or class:spec number).\n"
            "       -rio: Minimum RIO score to display (0-3500, default is 2000).\n"
            
            "\n/tournament - Get top players in each category.\n"            
            "       -guild: Top players of which guild will be searched.\n"
            "       -top: Top X players.\n"
            
            "\n/uwf - Ukrainian World First. Shows raid ranking history of Ukrainian guilds.\n"            
            "       -df: Shows only Dragonflight seasons and rankings.\n"
            "       -tww: Shows only The War Within seasons and rankings.\n"
            "       -champs: Displays guilds that finished 1st place at least once.\n"
            "       -stats: Displays all guilds that appeared in the rankings.\n"
            
            "\n/about_us - Learn more about us.\n"
            
            "\n/rules - Rules.\n"
            
            "\n/help - Get information about available commands.\n"
            
            "\nSourse code - https://github.com/CemXokenc/uawowguilds.\n"
        )
        
        await interaction.response.send_message(help_message)

    except Exception as e:
        print(f"An error occurred while processing the help command: {e}")
        await interaction.response.send_message("An error occurred while processing the command. Please try again later.")

# Event handler for bot readiness
@client.event
async def on_ready():
    # Synchronize the command tree    
    await tree.sync()
    print("Ready!")
    
# Event handler for new messages
@client.event
async def on_message(message):
    # Check myself
    if message.author == client.user:
        return
        
    if message.guild is None:
        return

    # Config    
    required_role = discord.utils.get(message.guild.roles, name="Guest")
    skiped_role = discord.utils.get(message.guild.roles, name="guild member")
    author = message.author.nick if isinstance(message.author, discord.Member) and message.author.nick else message.author.display_name    
    name_pattern = r"[|/(\[]"
    
    # Check if the message contains trigger text    
    if "видайте мені роль члена гільдії" in message.content.lower() and "флудилка" in message.channel.name:
        # If the author has the skiped_role, skip the checks
        if skiped_role in message.author.roles:
            await message.reply("You already have a role")            
        else:    
            # Check if the message author has a specific role and the message is sent in a specific channel
            if required_role not in message.author.roles or not re.search(name_pattern, author):
                # Check if the bot has permission to add reactions
                if message.channel.permissions_for(message.guild.me).add_reactions:
                    await message.add_reaction("⛔")
                else:
                    print("Bot does not have permission to add reactions in this channel.")
                    
                # Replying with a message
                await message.reply("https://cdn.discordapp.com/attachments/786720808788688918/1202356554523742289/image.png?ex=65e8d84d&is=65d6634d&hm=dee787e24cb77005a58568556547af37a24fe98bfcb11c1f6ecabc1bf72842ff&")
            
# Run the bot
client.run(token)
