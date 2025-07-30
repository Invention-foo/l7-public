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
    
    // Fetch exceptions for this chat
    const { data: exceptions, error } = await supabaseAdmin
      .from('athena_secure_tg_exceptions')
      .select(`
        id,
        user_id,
        created_at
      `)
      .eq('chat_id', chatId)
      .order('created_at', { ascending: false });
    
    if (error) {
      return NextResponse.json({ 
        success: false, 
        message: "Error fetching exceptions" 
      }, { status: 500 });
    }
    
    return NextResponse.json({
      success: true,
      data: {
        exceptions,
        chatId
      }
    });
  } catch (error) {
    console.error("Error getting exceptions:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 