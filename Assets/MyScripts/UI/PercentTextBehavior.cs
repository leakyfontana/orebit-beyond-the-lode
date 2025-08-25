using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;

public class PercentTextBehavior : MonoBehaviour
{
    // Start is called before the first frame update
    void Start()
    {
        
    }

    // Update is called once per frame
    void Update()
    {
        
    }
	
	public void setTextPercent0to1(float amount){
		GetComponent<TextMeshProUGUI>().text = Mathf.Round(amount * 100).ToString() + "%";
	}
}
