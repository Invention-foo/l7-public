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
    
    // Get parameters from query
    const { searchParams } = new URL(request.url);
    const walletAddress = searchParams.get('walletAddress');
    const limit = parseInt(searchParams.get('limit') || '100');
    
    if (!walletAddress) {
      return NextResponse.json({ 
        success: false, 
        message: "Wallet address is required" 
      }, { status: 400 });
    }
    
    // First get the user's telegram chat ID
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
    
    // Fetch team members for this chat
    const { data: teamMembers } = await supabaseAdmin
      .from('team')
      .select('telegram_id, telegram_chat_id')
      .eq('telegram_chat_id', chatId);
    
    // Create a Set of team member IDs for efficient lookup
    const teamMemberIds = new Set(teamMembers?.map(member => member.telegram_id) || []);
    
    // Fetch blacklisted user IDs
    const { data: blacklistedUsers, error: blacklistError } = await supabaseAdmin
      .from('blacklisted_tg_users')
      .select('user_id');
    
    if (blacklistError) {
      console.error("Error fetching blacklisted users:", blacklistError);
    }
    
    // Create a Set of blacklisted user IDs for efficient lookup
    const blacklistedUserIds = new Set(blacklistedUsers?.map(user => user.user_id) || []);
    
    // Fetch messages
    const { data: messages, error: messagesError } = await supabaseAdmin
      .from('athena_secure_tg_message_logs')
      .select(`
        id,
        message_text,
        created_at,
        athena_secure_tg_logs!inner(
          chat_id,
          user_id,
          content
        )
      `)
      .eq('athena_secure_tg_logs.chat_id', chatId)
      .order('created_at', { ascending: false })
      .limit(limit);
    
    if (messagesError) {
      return NextResponse.json({ 
        success: false, 
        message: "Error fetching messages" 
      }, { status: 500 });
    }
    
    return NextResponse.json({
      success: true,
      data: {
        messages,
        teamMemberIds: Array.from(teamMemberIds),
        blacklistedUserIds: Array.from(blacklistedUserIds),
        chatId
      }
    });
  } catch (error) {
    console.error("Error getting messages:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 