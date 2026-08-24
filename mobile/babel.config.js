module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    // Migrations are .sql files that must be compiled INTO the bundle — there
    // is no filesystem to read them from at runtime on a device.
    plugins: [['inline-import', { extensions: ['.sql'] }]],
  };
};
