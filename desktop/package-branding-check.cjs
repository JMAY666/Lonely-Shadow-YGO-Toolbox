'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {NtExecutable,NtExecutableResource} = require('pe-library');
const {Resource,Data} = require('resedit');
const brand = require('./branding.cjs');
const config = require('../package.json');
const executable = path.resolve(__dirname,'..',config.build.directories.output,'win-unpacked',config.build.win.executableName+'.exe');
const resources = NtExecutableResource.from(NtExecutable.from(fs.readFileSync(executable)));
const versions = Resource.VersionInfo.fromEntries(resources.entries).flatMap(info=>info.getAvailableLanguages().map(language=>info.getStringValues(language)));
assert(versions.some(version=>version.ProductName===brand.name));
assert(versions.some(version=>version.FileDescription===brand.name));
const source = Data.IconFile.from(fs.readFileSync(brand.icon));
const icons = Resource.IconGroupEntry.fromEntries(resources.entries).flatMap(group=>group.getIconItemsFromEntries(resources.entries));
for (const entry of source.icons) {
  assert(icons.some(icon=>icon.isRaw()&&entry.data.isRaw()&&Buffer.from(icon.bin).equals(Buffer.from(entry.data.bin))),
    `Packaged executable must contain source icon frame ${entry.data.width}x${entry.data.height}`);
}
console.log('PASS Packaged EXE product name, file description and all seven source icon frames');
