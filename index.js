require('dotenv').config();
const { Client, GatewayIntentBits } = require('discord.js');
const admin = require('firebase-admin');

admin.initializeApp({
  credential: admin.credential.cert({
    projectId: process.env.FIREBASE_PROJECT_ID,
    clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
    privateKey: process.env.FIREBASE_PRIVATE_KEY.replace(/\\n/g, '\n')
  })
});
const db = admin.firestore();

const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent]
});

client.once('ready', () => {
  console.log('bot online');
  client.user.setPresence({
    activities: [{ name: 'reps', type: 'WATCHING' }],
    status: 'online'
  }).catch(console.error);
});

client.on('interactionCreate', async interaction => {
  if (!interaction.isCommand()) return;
  if (interaction.commandName !== 'rep') return;

  // use flags instead of ephemeral property to avoid deprecation warning
  await interaction.deferReply({ flags: 64 }); // 64 = ephemeral flag

  const userOpt = interaction.options.getUser('user');
  const action = interaction.options.getString('action');
  const author = interaction.user;
  const guildId = interaction.guildId;

  try {
    if (action === 'leaderboard') {
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
      await interaction.editReply({ content: lb || 'no rep data' });
    } else if (action === 'profile') {
      const target = userOpt || author;
      const docId = `${guildId}_${target.id}`;
      const doc = await db.collection('reps').doc(docId).get();
      const count = doc.exists ? doc.data().count : 0;
      await interaction.editReply({ content: `<@${target.id}> has ${count} rep.` });
    } else {
      if (!userOpt) {
        const docId = `${guildId}_${author.id}`;
        const doc = await db.collection('reps').doc(docId).get();
        const count = doc.exists ? doc.data().count : 0;
        await interaction.editReply({ content: `you have ${count} rep.` });
      } else {
        if (userOpt.id === author.id) {
          await interaction.editReply({ content: "can't rep yourself" });
          return;
        }
        const docId = `${guildId}_${userOpt.id}`;
        const ref = db.collection('reps').doc(docId);
        await db.runTransaction(async t => {
          const doc = await t.get(ref);
          if (!doc.exists) t.set(ref, { guildId, userId: userOpt.id, count: 1 });
          else t.update(ref, { count: doc.data().count + 1 });
        });
        await interaction.editReply({ content: `rep given to <@${userOpt.id}>!` });
      }
    }
  } catch (error) {
    console.error('error in slash command:', error);
    try {
      await interaction.editReply({ content: 'an error occurred' });
    } catch (e) {
      console.error('error sending error reply:', e);
    }
  }
});

client.on('messageCreate', async message => {
  if (message.author.bot) return;
  console.log(`message received: ${message.content}`);
  const repWords = ['thanks', 'ty', 'tysm'];
  if (repWords.some(word => message.content.toLowerCase().includes(word))) {
    if (message.mentions.users.size > 0) {
      message.mentions.users.forEach(async user => {
        if (user.id === message.author.id) return;
        const docId = `${message.guild.id}_${user.id}`;
        const ref = db.collection('reps').doc(docId);
        try {
          await db.runTransaction(async t => {
            const doc = await t.get(ref);
            if (!doc.exists) t.set(ref, { guildId: message.guild.id, userId: user.id, count: 1 });
            else t.update(ref, { count: doc.data().count + 1 });
          });
          console.log(`added rep to ${user.tag} via message from ${message.author.tag}`);
        } catch (error) {
          console.error('error updating rep from message:', error);
        }
      });
    }
  }
});

client.login(process.env.DISCORD_TOKEN);
