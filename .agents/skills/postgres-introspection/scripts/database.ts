import { closeReadOnly, connectReadOnly } from './lib/db.js';
import { buildArtifact } from './lib/model.js';
import { renderComplete, writeEntityFiles } from './lib/render.js';
import { writeStateJson, writeStateText } from './lib/output.js';

// Database introspection. Reads the live PostgreSQL catalogs read-only and renders the whole
// database state directly into state/ three ways: the navigable JSON, the complete document,
// and one self-contained file per table, view, and function. The pipeline is connect, build
// the model, render, write. Each stage is a module: lib/db (connection and discovery),
// lib/catalog (queries), lib/model (assembly), lib/render (markdown), lib/output (writers).

async function main(): Promise<void> {
  const client = await connectReadOnly();
  try {
    const artifact = await buildArtifact(client);
    writeStateJson('database.json', artifact);
    writeStateText('database.md', renderComplete(artifact));
    writeEntityFiles(artifact);
    console.log(
      `Wrote state/database.json, state/database.md, and the state/database/ tree (as of migration ${artifact['version'] as string}).`,
    );
  } finally {
    await closeReadOnly(client);
  }
}

await main();
