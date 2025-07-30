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
    const query = searchParams.get('query');
    
    if (!walletAddress) {
      return NextResponse.json({ 
        success: false, 
        message: "Wallet address is required" 
      }, { status: 400 });
    }
    
    if (!query) {
      return NextResponse.json({ 
        success: false, 
        message: "Search query is required" 
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
    
    // Search messages using the RPC function
    const { data: messages, error: searchError } = await supabaseAdmin
      .rpc('search_messages', {
        p_chat_id: chatId,
        p_query: query
      });
    
    if (searchError) {
      return NextResponse.json({ 
        success: false, 
        message: "Error searching messages" 
      }, { status: 500 });
    }
    
    return NextResponse.json({
      success: true,
      data: messages
    });
  } catch (error) {
    console.error("Error searching messages:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 