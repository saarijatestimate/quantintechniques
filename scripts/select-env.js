const fs = require('fs');
const path = require('path');

const envName = process.argv[2];
const validEnvs = ['int', 'syst', 'accept'];

if (!envName || !validEnvs.includes(envName)) {
  console.error(`Usage: node scripts/select-env.js <int|syst|accept>`);
  process.exit(1);
}

const sourceFile = path.join(__dirname, '..', 'env', `${envName}.env`);
const targetFile = path.join(__dirname, '..', '.env');

try {
  const contents = fs.readFileSync(sourceFile, 'utf8');
  fs.writeFileSync(targetFile, contents);
  console.log(`Selected environment: ${envName}`);
} catch (error) {
  console.error(`Could not load environment file: ${sourceFile}`);
  console.error(error.message);
  process.exit(1);
}
