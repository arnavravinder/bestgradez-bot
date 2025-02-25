require('dotenv').config();
const { REST, Routes, ApplicationCommandOptionType } = require('discord.js');

const commands = [
  {
    name: 'rep',
    description: 'rep commands (give rep, leaderboard, profile)',
    options: [
      {
        name: 'user',
        description: 'target user for rep or profile',
        type: ApplicationCommandOptionType.User,
        required: false,
      },
      {
        name: 'action',
        description: 'choose action: leaderboard or profile',
        type: ApplicationCommandOptionType.String,
        required: false,
        choices: [
          { name: 'leaderboard', value: 'leaderboard' },
          { name: 'profile', value: 'profile' },
        ],
      },
    ],
  },
];

if (!process.env.DISCORD_TOKEN || !process.env.CLIENT_ID) {
  console.error('missing env vars: set DISCORD_TOKEN and CLIENT_ID in your .env');
  process.exit(1);
}

const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);

(async () => {
  try {
    console.log('started refreshing slash commands');
    if (process.env.GUILD_ID) {
      await rest.put(
        Routes.applicationGuildCommands(process.env.CLIENT_ID, process.env.GUILD_ID),
        { body: commands }
      );
      console.log('registered commands in guild');
    } else {
      await rest.put(
        Routes.applicationCommands(process.env.CLIENT_ID),
        { body: commands }
      );
      console.log('registered global commands');
    }
  } catch (err) {
    console.error(err);
  }
})();
