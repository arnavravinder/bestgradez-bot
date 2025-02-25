// load env vars
require('dotenv').config();
const { Client, GatewayIntentBits } = require('discord.js');
const admin = require('firebase-admin');

// firebase init
admin.initializeApp({
  credential: admin.credential.cert({
    projectId: process.env.FIREBASE_PROJECT_ID,
    clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
    privateKey: process.env.FIREBASE_PRIVATE_KEY.replace(/\\n/g, '\n')
  })
});
const db = admin.firestore();

// create discord client
const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent]
});

// on bot ready
client.on('ready', () => {
  console.log('bot online');
});

// handle slash commands
client.on('interactionCreate', async interaction => {
  if (!interaction.isCommand()) return;
  if (interaction.commandName !== 'rep') return;
  
  const userOpt = interaction.options.getUser('user');
  const action = interaction.options.getString('action');
  const author = interaction.user;
  const guildId = interaction.guildId;
  
  if (action === 'leaderboard') {
    // get top 10 for guild
    const snap = await db.collection('reps')
      .where('guildId', '==', guildId)
      .orderBy('count', 'desc')
      .limit(10)
      .get();
    let lb = '';
    let rank = 1;
    snap.forEach(doc => {
      const data = doc.data();
      lb += `${rank}. <@${data.userId}> - ${data.count}\n`;
      rank++;
    });
    await interaction.reply({ content: lb || 'no rep data', ephemeral: true });
  }
  else if (action === 'profile') {
    const target = userOpt || author;
    const docId = `${guildId}_${target.id}`;
    const doc = await db.collection('reps').doc(docId).get();
    const count = doc.exists ? doc.data().count : 0;
    await interaction.reply({ content: `<@${target.id}> has ${count} rep.`, ephemeral: true });
  }
  else {
    // no action = rep given (or if only user provided, else show own profile)
    if (!userOpt) {
      const docId = `${guildId}_${author.id}`;
      const doc = await db.collection('reps').doc(docId).get();
      const count = doc.exists ? doc.data().count : 0;
      await interaction.reply({ content: `you have ${count} rep.`, ephemeral: true });
    } else {
      if (userOpt.id === author.id) {
        await interaction.reply({ content: "can't rep yourself", ephemeral: true });
        return;
      }
      const docId = `${guildId}_${userOpt.id}`;
      const ref = db.collection('reps').doc(docId);
      await db.runTransaction(async t => {
        const doc = await t.get(ref);
        if (!doc.exists) t.set(ref, { guildId, userId: userOpt.id, count: 1 });
        else t.update(ref, { count: doc.data().count + 1 });
      });
      await interaction.reply({ content: `rep given to <@${userOpt.id}>!`, ephemeral: true });
    }
  }
});

// detect text messages for rep words
client.on('messageCreate', async message => {
  if (message.author.bot) return;
  const repWords = ['thanks', 'ty', 'tysm'];
  if (repWords.some(word => message.content.toLowerCase().includes(word))) {
    if (message.mentions.users.size > 0) {
      message.mentions.users.forEach(async user => {
        if (user.id === message.author.id) return;
        const docId = `${message.guild.id}_${user.id}`;
        const ref = db.collection('reps').doc(docId);
        await db.runTransaction(async t => {
          const doc = await t.get(ref);
          if (!doc.exists) t.set(ref, { guildId: message.guild.id, userId: user.id, count: 1 });
          else t.update(ref, { count: doc.data().count + 1 });
        });
      });
    }
  }
});
// on bot ready
client.on('ready', () => {
    console.log('bot online');
    client.user.setPresence({
      activities: [{ name: 'reps', type: 'WATCHING' }],
      status: 'online'
    });
  });
  
client.login(process.env.DISCORD_TOKEN);
