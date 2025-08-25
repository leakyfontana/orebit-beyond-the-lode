using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;

public class PopupManager : MonoBehaviour
{
	private GameObject current_ui_element_displayed;
	public GameObject text_container;

    // Start is called before the first frame update
    void Start()
    {
        
    }

    // Update is called once per frame
    void Update()
    {
        
    }

	public void openPopup(string text, double open_time = 0, GameObject current_ui_to_disable = null){
		//disable ui
		Debug.Log("popup opened with: " + text);
		text_container.GetComponent<SlowTextDisplayer>().setText(text);
		gameObject.SetActive(true);
	}
	
	public void openPopupWithoutSlowTextDisplayer(string text, double open_time = 0, GameObject current_ui_to_disable = null){
		//disable ui
		Debug.Log("popup opened with: " + text);
		text_container.GetComponent<TextMeshProUGUI>().text = text;
		gameObject.SetActive(true);
	}

	public void closePopup(){
		//enable UI
		gameObject.SetActive(false);
	}
}
