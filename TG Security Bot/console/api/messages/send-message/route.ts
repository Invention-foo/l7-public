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

    const { walletAddress, message } = await request.json()
    
    if (!walletAddress || !message) {
      return NextResponse.json({
        success: false,
        message: 'Wallet address and message are required'
      }, { status: 400 })
    }
    
    // Get bot token from environment variables
    const botToken = process.env.NEOGUARD_BOT_TOKEN
    if (!botToken) {
      return NextResponse.json({
        success: false,
        message: 'Telegram bot not configured'
      }, { status: 500 })
    }
    
    // Get user's telegram chat ID from neoguard_users table
    const { data: userData, error: userError } = await supabaseAdmin
      .from('neoguard_users')
      .select('telegram_chat_id')
      .eq('wallet_address', walletAddress)
      .single()
    
    if (userError || !userData) {
      return NextResponse.json({
        success: false,
        message: 'User not found or not authorized'
      }, { status: 404 })
    }
    
    const { telegram_chat_id } = userData

    console.log('telegram_chat_id', telegram_chat_id)
    
    if (!telegram_chat_id) {
      return NextResponse.json({
        success: false,
        message: 'Telegram chat not configured. Please connect your Telegram first.'
      }, { status: 400 })
    }
    
    // Send message via Telegram Bot API
    console.log('Attempting to send message to chat:', telegram_chat_id)
    
    const telegramUrl = `https://api.telegram.org/bot${botToken}/sendMessage?chat_id=${telegram_chat_id}&text=${encodeURIComponent(message)}&parse_mode=HTML`
    
    console.log('Telegram URL:', telegramUrl)
    const telegramResponse = await fetch(telegramUrl, {
      method: 'GET'
    })
    
    const telegramResult = await telegramResponse.json()
    console.log('Telegram API response:', telegramResult)
    
    if (!telegramResponse.ok) {
      console.error('Telegram API error:', telegramResult)
      return NextResponse.json({
        success: false,
        message: `Failed to send message: ${telegramResult.description || 'Unknown error'}`,
        debug: {
          chatId: telegram_chat_id,
          chatIdType: typeof telegram_chat_id,
          telegramError: telegramResult,
          url: telegramUrl
        }
      }, { status: 500 })
    }
    
    // Log the sent message following the same pattern as Python codebase
    try {
      // First insert into athena_secure_tg_logs
      const { data: logData, error: logError } = await supabaseAdmin
        .from('athena_secure_tg_logs')
        .insert({
          log_type: 'message',
          user_id: 'NeoGuard', // Bot sent message, so no user_id
          chat_id: telegram_chat_id.toString(),
          content: `Bot sent message: ${message}`
        })
        .select('id')
        .single()
      
      if (logError) {
        console.error('Error inserting main log:', logError)
      } else if (logData) {
        // Then insert into athena_secure_tg_message_logs using the returned log_id
        const { error: messageLogError } = await supabaseAdmin
          .from('athena_secure_tg_message_logs')
          .insert({
            log_id: logData.id,
            message_text: `[BOT SENT] ${message}`,
            message_type: 'bot_sent'
          })
        
        if (messageLogError) {
          console.error('Error inserting message log:', messageLogError)
        }
      }
    } catch (logError) {
      console.error('Error logging message:', logError)
      // Don't fail the API call if logging fails
    }
    
    return NextResponse.json({
      success: true,
      message: 'Message sent successfully',
      data: {
        messageId: telegramResult.result.message_id,
        sentAt: new Date().toISOString()
      }
    })
    
  } catch (error) {
    console.error('Error sending message:', error)
    return NextResponse.json({
      success: false,
      message: 'Internal server error'
    }, { status: 500 })
  }
} 