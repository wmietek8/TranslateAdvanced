# -*- coding: utf-8 -*-
# Copyright (C) 2024 Your Name <youremail@example.com>

import addonHandler
import logHandler
import json
import urllib.request
import urllib.error
import threading
from urllib.parse import quote

addonHandler.initTranslation()

class TranslatorGemini:
    def __init__(self):
        self.error = {"success": False, "data": None}
        self.translator_thread = None

    def translate_gemini(self, api_key, text, target_language="es", source_language="auto", show_progress=False, widget=None):
        self.error = {"success": False, "data": None} # Reset error status
        # Store source_language, though Gemini might auto-detect
        self.source_language = source_language

        self.translator_thread = self.TranslatorThread(
            text,
            target_language,
            source_language,
            api_key,
            show_progress,
            widget
        )
        self.translator_thread.start()
        self.translator_thread.join()  # Wait for the thread to complete

        if self.translator_thread.error["data"]:
            self.error = self.translator_thread.error
            logHandler.log.error(f"Gemini API error: {self.error['data']}")
            return text # Return original text on error

        translation = self.translator_thread.translation
        if not translation: # If translation is empty (e.g. thread stopped)
             logHandler.log.info("Gemini translation was empty or thread was stopped.")
             return text
        return translation

    def get_error(self):
        return self.error

    def stop(self):
        if self.translator_thread and self.translator_thread.is_alive():
            self.translator_thread.stop()
            # self.translator_thread.join() # Optionally wait for thread to acknowledge stop

    class TranslatorThread(threading.Thread):
        def __init__(self, text, target_language, source_language, api_key, show_progress, widget):
            super().__init__()
            self.text = text
            self.target_language = target_language
            self.source_language = source_language # Used in prompt
            self.api_key = api_key
            self.show_progress = show_progress # Currently unused, for future progress implementation
            self.widget = widget # Currently unused, for future progress implementation

            self.translation = ''
            self.error = {"success": False, "data": None}
            
            self.opener = urllib.request.build_opener()
            self.opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
            
            self._stop_event = threading.Event()
            
            # For future progress implementation
            # self.total_chunks = 1 
            # self.processed_chunks = 0

        def stop(self):
            self._stop_event.set()
            logHandler.log.debug("TranslatorThread stop event set")

        def run(self):
            if self._stop_event.is_set():
                self.error = {"success": True, "data": "Translation stopped by user."}
                logHandler.log.info("Translation thread stopping as stop event is set.")
                return

            # Construct the prompt
            # Using f-string for clarity, ensure self.text is properly escaped if it can contain quotes.
            # For now, assuming self.text is plain text.
            # If source_language is 'auto', Gemini will attempt to detect it.
            # The prompt guides Gemini on the task.
            prompt = f"Translate the following text from '{self.source_language}' to '{self.target_language}'. If the source language is 'auto', detect the language of the text. Do not change proper names or brand names. Provide only the translated text, without any additional explanations or introductory phrases: '{self.text}'"

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={self.api_key}"
            headers = {"Content-Type": "application/json"}
            
            data = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt
                            }
                        ]
                    }
                ]
            }
            json_data = json.dumps(data).encode('utf-8')

            try:
                logHandler.log.debug(f"Gemini API request URL: {url}")
                # logHandler.log.debug(f"Gemini API request data: {json_data}") # Avoid logging potentially large text
                req = urllib.request.Request(url, data=json_data, headers=headers, method='POST')
                with self.opener.open(req, timeout=20) as response: # 20 seconds timeout
                    response_body = response.read().decode('utf-8')
                    logHandler.log.debug(f"Gemini API response status: {response.status}")
                    # logHandler.log.debug(f"Gemini API response body: {response_body}") # Avoid logging potentially large response

                    if self._stop_event.is_set():
                        self.error = {"success": True, "data": "Translation stopped during API response processing."}
                        logHandler.log.info("Translation thread stopping after API call, stop event is set.")
                        return

                    response_json = json.loads(response_body)

                    if 'candidates' in response_json and response_json['candidates']:
                        candidate = response_json['candidates'][0]
                        if 'content' in candidate and 'parts' in candidate['content'] and candidate['content']['parts']:
                            self.translation = candidate['content']['parts'][0]['text'].strip()
                            self.error = {"success": True, "data": None}
                            # logHandler.log.debug(f"Gemini translation: {self.translation}")
                        else:
                            error_detail = "Missing 'parts' in Gemini response content."
                            logHandler.log.error(error_detail + f" Response: {response_json}")
                            self.error = {"success": False, "data": error_detail}
                    elif 'error' in response_json:
                        error_detail = response_json['error'].get('message', 'Unknown API error')
                        logHandler.log.error(f"Gemini API error: {error_detail}. Full response: {response_json}")
                        self.error = {"success": False, "data": f"API Error: {error_detail}"}
                    else:
                        error_detail = "Unexpected Gemini API response structure."
                        logHandler.log.error(error_detail + f" Response: {response_json}")
                        self.error = {"success": False, "data": error_detail}

            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8') if e.fp else "No error body"
                logHandler.log.error(f"Gemini API HTTPError: {e.code} {e.reason}. Body: {error_body}")
                try:
                    error_json = json.loads(error_body)
                    self.error = {"success": False, "data": error_json.get('error', {}).get('message', f"HTTPError {e.code}")}
                except json.JSONDecodeError:
                    self.error = {"success": False, "data": f"HTTPError {e.code}: {e.reason}. Non-JSON error body: {error_body}"}
            except urllib.error.URLError as e:
                logHandler.log.error(f"Gemini API URLError: {e.reason}")
                self.error = {"success": False, "data": f"URLError: {e.reason}"}
            except json.JSONDecodeError as e:
                logHandler.log.error(f"Error decoding JSON response from Gemini API: {e}")
                self.error = {"success": False, "data": f"JSONDecodeError: {e}"}
            except Exception as e:
                logHandler.log.error(f"Unexpected error during Gemini API call: {e}", exc_info=True)
                self.error = {"success": False, "data": f"Unexpected error: {str(e)}"}
            
            # For future progress:
            # if self.error["success"] and not self.error["data"]:
            #    self.processed_chunks += 1
            #    if self.widget and self.show_progress:
            #        self.widget(self.get_progress())
            
            if self._stop_event.is_set():
                 logHandler.log.info("Translation thread finished but stop event was set before completion.")
                 # Potentially override error if one was not already set by stop() itself
                 if not self.error["data"] and not self.translation :
                     self.error = {"success": True, "data": "Translation stopped."}


        def get_progress(self):
            # Basic progress, assuming one chunk for now
            # if not self.total_chunks: return 0
            # return (self.processed_chunks / self.total_chunks) * 100
            return 100 # Placeholder until chunking is implemented
