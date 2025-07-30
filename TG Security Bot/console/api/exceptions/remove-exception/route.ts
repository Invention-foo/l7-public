import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { ethers } from 'ethers';

// Initialize Supabase admin client (server-side only)
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || '';

// Make sure we have the required environment variables
if (!supabaseUrl || !supabaseServiceKey) {
  console.error("Missing Supabase environment variables");
}

const supabaseAdmin = createClient(supabaseUrl, supabaseServiceKey);

export async function POST(request: Request) {
  try {
    // Check if Supabase is properly initialized
    if (!supabaseUrl || !supabaseServiceKey) {
      return NextResponse.json({ 
        success: false, 
        message: "Server configuration error" 
      }, { status: 500 });
    }
    
    // Get request body
    const body = await request.json();
    const { walletAddress, userId, signature, message, timestamp } = body;
    
    if (!walletAddress || !userId || !signature || !message || !timestamp) {
      return NextResponse.json({ 
        success: false, 
        message: "Missing required fields" 
      }, { status: 400 });
    }
    
    // Verify the signature
    const expectedMessage = `Remove exception for user ${userId} at timestamp ${timestamp}`;
    if (message !== expectedMessage) {
      return NextResponse.json({ 
        success: false, 
        message: "Invalid message format" 
      }, { status: 400 });
    }
    
    // Check if the timestamp is recent (within 5 minutes)
    const now = Date.now();
    if (now - timestamp > 5 * 60 * 1000) {
      return NextResponse.json({ 
        success: false, 
        message: "Signature expired" 
      }, { status: 400 });
    }
    
    // Verify the signature matches the wallet address
    const signerAddress = ethers.verifyMessage(message, signature);
    if (signerAddress.toLowerCase() !== walletAddress.toLowerCase()) {
      return NextResponse.json({ 
        success: false, 
        message: "Invalid signature" 
      }, { status: 401 });
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
    
    // Remove the exception
    const { error } = await supabaseAdmin
      .from('athena_secure_tg_exceptions')
      .delete()
      .eq('chat_id', chatId)
      .eq('user_id', userId);
    
    if (error) {
      return NextResponse.json({ 
        success: false, 
        message: "Error removing exception" 
      }, { status: 500 });
    }
    
    return NextResponse.json({
      success: true,
      message: "Exception removed successfully"
    });
  } catch (error) {
    console.error("Error removing exception:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 