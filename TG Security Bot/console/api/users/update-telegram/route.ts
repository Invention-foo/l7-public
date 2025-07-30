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
    
    // Get request data
    const { walletAddress, telegramChatId, signature, message, timestamp } = await request.json();
    
    // Validate inputs
    if (!walletAddress || !telegramChatId || !signature || !message || !timestamp) {
      return NextResponse.json({ 
        success: false, 
        message: "Missing required parameters" 
      }, { status: 400 });
    }
    
    // Check if timestamp is recent (within 5 minutes)
    const currentTime = Date.now();
    if (currentTime - timestamp > 5 * 60 * 1000) {
      return NextResponse.json({ 
        success: false, 
        message: "Signature expired" 
      }, { status: 401 });
    }
    
    // Verify the signature
    try {
      const recoveredAddress = ethers.verifyMessage(message, signature);
      
      if (recoveredAddress.toLowerCase() !== walletAddress.toLowerCase()) {
        return NextResponse.json({ 
          success: false, 
          message: "Invalid signature" 
        }, { status: 401 });
      }
    } catch (error) {
      console.error("Signature verification error:", error);
      return NextResponse.json({ 
        success: false, 
        message: "Signature verification failed" 
      }, { status: 401 });
    }
    
    // Check if the Telegram Chat ID is already in use by another user
    const { data: existingTelegramChatId } = await supabaseAdmin
      .from("neoguard_users")
      .select("wallet_address")
      .eq("telegram_chat_id", telegramChatId)
      .neq("wallet_address", walletAddress)
      .single();
    
    if (existingTelegramChatId) {
      return NextResponse.json({ 
        success: false, 
        message: "This Telegram Chat ID is already in use." 
      }, { status: 409 }); // 409 Conflict
    }
    
    // Update the user's Telegram chat ID
    const { error: updateError } = await supabaseAdmin
      .from("neoguard_users")
      .update({ 
        telegram_chat_id: telegramChatId || null,
        updated_at: new Date().toISOString()
      })
      .eq("wallet_address", walletAddress);
    
    if (updateError) {
      console.error("Database update error:", updateError);
      return NextResponse.json({ 
        success: false, 
        message: "Failed to update database" 
      }, { status: 500 });
    }
    
    return NextResponse.json({
      success: true,
      message: "Telegram chat ID updated successfully"
    });
  } catch (error) {
    console.error("Error updating telegram chat ID:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 