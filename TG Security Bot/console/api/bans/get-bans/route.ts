/* eslint-disable */
import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

// Initialize Supabase admin client (server-side only)
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || '';

// Make sure we have the required environment variables
if (!supabaseUrl || !supabaseServiceKey) {
  console.error("Missing Supabase environment variables");
}

const supabaseAdmin = createClient(supabaseUrl, supabaseServiceKey);

function extractUsername(content: string): string {
  const banPatterns = [
    /Banned user (.+) for/,
    /Banned new member (.+) for/
  ]
  
  for (const pattern of banPatterns) {
    const match = content.match(pattern)
    if (match) return match[1]
  }
  
  return 'Unknown User'
}

function extractReason(content: string): string {
  const match = content.match(/for (.+)$/)
  return match ? match[1] : 'Unknown reason'
}

export async function GET(request: Request) {
  try {
    // Check if Supabase is properly initialized
    if (!supabaseUrl || !supabaseServiceKey) {
      return NextResponse.json({ 
        success: false, 
        message: "Server configuration error" 
      }, { status: 500 });
    }
    
    // Get wallet address from query params
    const { searchParams } = new URL(request.url);
    const walletAddress = searchParams.get('walletAddress');
    
    if (!walletAddress) {
      return NextResponse.json({ 
        success: false, 
        message: "Wallet address is required" 
      }, { status: 400 });
    }
    
    // Get user's telegram chat ID
    const { data: userData, error: userError } = await supabaseAdmin
      .from('neoguard_users')
      .select('telegram_chat_id')
      .eq('wallet_address', walletAddress)
      .single();
    
    if (userError || !userData) {
      return NextResponse.json({ 
        success: false, 
        message: "User not found" 
      }, { status: 404 });
    }
    
    const chatId = userData.telegram_chat_id;
    
    if (!chatId) {
      return NextResponse.json({ 
        success: false, 
        message: "No Telegram chat ID found for this user" 
      }, { status: 404 });
    }
    
    // Fetch ban logs with reason
    const { data: bans, error: bansError } = await supabaseAdmin
      .from('athena_secure_tg_moderation_logs')
      .select(`
        id,
        created_at,
        log_id,
        reason,
        athena_secure_tg_logs!inner(
          chat_id,
          user_id,
          content
        )
      `)
      .eq('athena_secure_tg_logs.chat_id', chatId)
      .eq('action_type', 'ban')
      .order('created_at', { ascending: false });
    
    if (bansError) {
      return NextResponse.json({ 
        success: false, 
        message: "Error fetching ban logs" 
      }, { status: 500 });
    }
    
    // For spam bans, fetch associated messages
    const spamBans = bans.filter(ban => ban.reason === 'spam');
    
    // Create an array of promises, one for each spam-banned user
    const spamMessagePromises = spamBans.map(ban => 
      supabaseAdmin
        .from('athena_secure_tg_logs')
        .select(`
          id,
          user_id,
          created_at,
          athena_secure_tg_message_logs!inner(
            message_text
          )
        `)
        .eq('log_type', 'message')
        // @ts-ignore
        .eq('user_id', ban.athena_secure_tg_logs.user_id)
        .lt('created_at', ban.created_at)
        .order('created_at', { ascending: false })
        .limit(1)
        .single()
    );
    
    // Wait for all queries to complete
    const spamMessagesResults = await Promise.all(spamMessagePromises);
    
    // Create a map using user_id as the key
    const messageMap = new Map(
      spamMessagesResults
        .filter(result => result.data && spamBans.some(ban => 
          // @ts-ignore
          ban.athena_secure_tg_logs.user_id === result.data.user_id
        ))
        .map(result => [
          // @ts-ignore
          result.data.user_id,
          // @ts-ignore
          result.data.athena_secure_tg_message_logs[0]?.message_text
        ])
    );
    
    // Fetch global ban status for all users
    const { data: globalBans } = await supabaseAdmin
      .from('blacklisted_tg_users')
      .select('user_id');
    
    const globalBanSet = new Set(globalBans?.map(ban => ban.user_id) || []);
    
    // Fetch existing reviews
    const { data: existingReviews } = await supabaseAdmin
      .from('athena_secure_review')
      .select('user_id')
      .eq('platform', 'telegram')
      .not('reviewed', 'eq', true);
    
    const reviewedUserIds = new Set(existingReviews?.map(review => review.user_id) || []);
    
    // Update banLogs mapping to include reviewed status
    const banLogs = bans.map(ban => ({
      // @ts-ignore
      user: extractUsername(ban.athena_secure_tg_logs.content),
      // @ts-ignore
      userId: ban.athena_secure_tg_logs.user_id,
      // @ts-ignore
      reason: ban.reason || extractReason(ban.athena_secure_tg_logs.content),
      chat: "Your Community",
      timestamp: ban.created_at,
      // @ts-ignore
      globalBan: globalBanSet.has(ban.athena_secure_tg_logs.user_id),
      // @ts-ignore
      spamMessage: messageMap.get(ban.athena_secure_tg_logs.user_id),
      // @ts-ignore
      reviewed: reviewedUserIds.has(ban.athena_secure_tg_logs.user_id)
    }));
    
    return NextResponse.json({
      success: true,
      data: banLogs
    });
  } catch (error) {
    console.error("Error getting ban logs:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 