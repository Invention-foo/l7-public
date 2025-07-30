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

export async function GET(request: Request) {
  try {
    // Check if Supabase is properly initialized
    if (!supabaseUrl || !supabaseServiceKey) {
      return NextResponse.json({ 
        success: false, 
        message: "Server configuration error" 
      }, { status: 500 });
    }
    
    // Get chat ID from query params
    const { searchParams } = new URL(request.url);
    const chatId = searchParams.get('chatId');
    
    if (!chatId) {
      return NextResponse.json({ 
        success: false, 
        message: "Chat ID is required" 
      }, { status: 400 });
    }
    
    // Fetch user-specific stats
    const [
      { count: userBans },
      { count: userMessages },
      { count: spamMessages }
    ] = await Promise.all([
      supabaseAdmin
        .from('athena_secure_tg_moderation_logs')
        .select('*, athena_secure_tg_logs!inner(chat_id)', { count: 'exact', head: true })
        .eq('athena_secure_tg_logs.chat_id', chatId)
        .eq('action_type', 'ban'),
      supabaseAdmin
        .from('athena_secure_tg_message_logs')
        .select('*, athena_secure_tg_logs!inner(chat_id)', { count: 'exact', head: true })
        .eq('athena_secure_tg_logs.chat_id', chatId),
      supabaseAdmin
        .from('athena_secure_tg_moderation_logs')
        .select('*, athena_secure_tg_logs!inner(chat_id)', { count: 'exact', head: true })
        .eq('athena_secure_tg_logs.chat_id', chatId)
        .eq('action_type', 'delete')
    ]);

    // Parallel data fetching for network stats
    const [
      { count: totalBans },
      { count: totalMessages },
      { count: spamDeleted },
      { count: blacklistedUsers }
    ] = await Promise.all([
      supabaseAdmin
        .from('athena_secure_tg_moderation_logs')
        .select('*', { count: 'exact', head: true })
        .eq('action_type', 'ban'),
      supabaseAdmin
        .from('athena_secure_tg_message_logs')
        .select('*', { count: 'exact', head: true }),
      supabaseAdmin
        .from('athena_secure_tg_moderation_logs')
        .select('*', { count: 'exact', head: true })
        .eq('action_type', 'delete'),
      supabaseAdmin
        .from('blacklisted_tg_users')
        .select('*', { count: 'exact', head: true })
    ]);

    // Get time series data
    const [banRates, messageRates] = await Promise.all([
      supabaseAdmin.rpc('get_time_series_data', {
        p_chat_id: chatId,
        p_table: 'moderation',
        p_timeframe: 'daily',
        p_action_type: 'ban'
      }),
      supabaseAdmin.rpc('get_time_series_data', {
        p_chat_id: chatId,
        p_table: 'message',
        p_timeframe: 'daily'
      })
    ]);

    // Prepare dashboard data
    const dashboardData = {
      userChat: {
        usersBanned: userBans ?? 0,
        messagesScanned: userMessages ?? 0,
        spamMessagesDeleted: spamMessages ?? 0,
      },
      partnerNetwork: {
        totalUsersBanned: totalBans ?? 0,
        totalMessagesScanned: totalMessages ?? 0,
        totalSpamDeleted: spamDeleted ?? 0,
        globalBlacklistedUsers: blacklistedUsers ?? 0,
      },
      banRateOverTime: banRates?.data || [],
      messageRateOverTime: messageRates?.data || [],
      chatId: chatId
    };
    
    return NextResponse.json({
      success: true,
      data: dashboardData
    });
  } catch (error) {
    console.error("Error getting dashboard stats:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 