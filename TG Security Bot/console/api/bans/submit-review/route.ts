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
    const { userId, messageText, walletAddress } = body;
    
    if (!userId || !messageText || !walletAddress) {
      return NextResponse.json({ 
        success: false, 
        message: "Missing required fields" 
      }, { status: 400 });
    }
    
    // Verify the user exists
    const { data: userData, error: userError } = await supabaseAdmin
      .from('neoguard_users')
      .select('id')
      .eq('wallet_address', walletAddress)
      .single();
    
    if (userError || !userData) {
      return NextResponse.json({ 
        success: false, 
        message: "User not found" 
      }, { status: 404 });
    }
    
    // Submit the review
    const { error } = await supabaseAdmin
      .from('athena_secure_review')
      .insert({
        platform: 'telegram',
        user_id: userId,
        ban_reason: 'spam',
        note: messageText
      });
    
    if (error) {
      return NextResponse.json({ 
        success: false, 
        message: "Error submitting review" 
      }, { status: 500 });
    }
    
    return NextResponse.json({
      success: true,
      message: "Review submitted successfully"
    });
  } catch (error) {
    console.error("Error submitting review:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 