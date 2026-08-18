import { createClient } from "@supabase/supabase-js";

// Server-only: never import this from a "use client" component. Keeping the
// Supabase key out of client bundles is the point - see agent/db/supabase_client.py
// for the same pattern on the agent side.
export function getSupabaseServerClient() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_KEY;
  if (!url || !key) {
    throw new Error("SUPABASE_URL and SUPABASE_KEY must be set in the environment");
  }
  return createClient(url, key);
}
