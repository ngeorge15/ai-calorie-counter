const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
// Let Metro treat .sql migration files as source so inline-import can embed them.
config.resolver.sourceExts.push('sql');

module.exports = config;
