import { NextRequest, NextResponse } from "next/server";
import { getSupabaseServerClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

// PostgREST's .or() filter syntax treats "," "(" ")" as structural
// characters - stripping them from user search input prevents a crafted
// search string from injecting extra filter conditions.
function sanitizeSearchTerm(raw: string): string {
  return raw.replace(/[,()]/g, "").replace(/[%_]/g, (c) => `\\${c}`);
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const minScoreParam = searchParams.get("minScore");
  const minScore = minScoreParam !== null ? Number(minScoreParam) : 33;
  const source = searchParams.get("source");
  const search = searchParams.get("search")?.trim();

  if (Number.isNaN(minScore)) {
    return NextResponse.json({ error: "minScore must be a number" }, { status: 400 });
  }

  let query = getSupabaseServerClient()
    .from("signals")
    .select("*")
    .gte("relevance_score", minScore)
    .order("relevance_score", { ascending: false })
    .limit(100);

  if (source && source !== "ALL") {
    query = query.eq("source", source);
  }

  if (search) {
    const term = sanitizeSearchTerm(search);
    query = query.or(`title.ilike.%${term}%,entity.ilike.%${term}%`);
  }

  const { data, error } = await query;

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data ?? []);
}
